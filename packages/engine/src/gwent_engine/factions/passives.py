from dataclasses import replace
from typing import override

from gwent_engine.cards import CardRegistry
from gwent_engine.core import CardType, FactionId, PassiveKind, Zone
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import CardsDrawnEvent, FactionPassiveTriggeredEvent, GameEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import CardInstance, GameState, PlayerState
from gwent_engine.rules.leader_common import pick_random_card_ids
from gwent_engine.rules.players import replace_player
from gwent_engine.rules.round_resolution import RoundOutcome
from gwent_engine.rules.state_ops import (
    append_to_row,
    drawable_card_ids,
    replace_card_instance,
    replace_card_instances,
)

PASSIVE_KIND_BY_FACTION = {
    player_faction: passive_kind
    for player_faction, passive_kind in (
        (FactionId.MONSTERS, PassiveKind.MONSTERS_KEEP_ONE_UNIT),
        (FactionId.NILFGAARD, PassiveKind.NILFGAARD_WINS_TIES),
        (FactionId.NORTHERN_REALMS, PassiveKind.NORTHERN_REALMS_DRAW_ON_ROUND_WIN),
        (FactionId.SCOIATAEL, PassiveKind.SCOIATAEL_CHOOSES_STARTING_PLAYER),
        (
            FactionId.SKELLIGE,
            PassiveKind.SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE,
        ),
    )
}


class FactionPassive:
    def choose_starting_player(
        self,
        state: GameState,
        owner: PlayerState,
        requested_starting_player: PlayerId,
        *,
        event_id_start: int,
    ) -> tuple[PlayerId, tuple[GameEvent, ...]]:
        del state, owner, event_id_start
        return requested_starting_player, ()

    def modify_round_outcome(
        self,
        state: GameState,
        owner: PlayerState,
        outcome: RoundOutcome,
        *,
        event_id_start: int,
    ) -> tuple[RoundOutcome, tuple[GameEvent, ...]]:
        del state, owner, event_id_start
        return outcome, ()

    def before_round_cleanup(
        self,
        state: GameState,
        owner: PlayerState,
        *,
        card_registry: CardRegistry,
        rng: SupportsRandom | None,
        event_id_start: int,
    ) -> tuple[frozenset[CardInstanceId], tuple[GameEvent, ...]]:
        del state, owner, card_registry, rng, event_id_start
        return frozenset(), ()

    def after_round_winner_finalized(
        self,
        state: GameState,
        owner: PlayerState,
        outcome: RoundOutcome,
        *,
        event_id_start: int,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        del owner, outcome, event_id_start
        return state, ()

    def on_round_start(
        self,
        state: GameState,
        owner: PlayerState,
        *,
        card_registry: CardRegistry,
        rng: SupportsRandom | None,
        event_id_start: int,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        del owner, card_registry, rng, event_id_start
        return state, ()


class ScoiataelPassive(FactionPassive):
    @override
    def choose_starting_player(
        self,
        state: GameState,
        owner: PlayerState,
        requested_starting_player: PlayerId,
        *,
        event_id_start: int,
    ) -> tuple[PlayerId, tuple[GameEvent, ...]]:
        scoiatael_players = tuple(
            player
            for player in state.players
            if passive_kind_for_player(player) == PassiveKind.SCOIATAEL_CHOOSES_STARTING_PLAYER
        )
        if len(scoiatael_players) != 1 or scoiatael_players[0].player_id != owner.player_id:
            return requested_starting_player, ()
        return requested_starting_player, (
            FactionPassiveTriggeredEvent(
                event_id=event_id_start,
                player_id=owner.player_id,
                passive_kind=PassiveKind.SCOIATAEL_CHOOSES_STARTING_PLAYER,
                chosen_player_id=requested_starting_player,
            ),
        )


class NilfgaardPassive(FactionPassive):
    @override
    def modify_round_outcome(
        self,
        state: GameState,
        owner: PlayerState,
        outcome: RoundOutcome,
        *,
        event_id_start: int,
    ) -> tuple[RoundOutcome, tuple[GameEvent, ...]]:
        if not outcome.is_draw:
            return outcome, ()

        nilfgaard_players = tuple(
            player
            for player in state.players
            if passive_kind_for_player(player) == PassiveKind.NILFGAARD_WINS_TIES
        )
        if len(nilfgaard_players) != 1 or nilfgaard_players[0].player_id != owner.player_id:
            return outcome, ()

        loser = next(
            player.player_id for player in state.players if player.player_id != owner.player_id
        )
        updated_outcome = RoundOutcome(scores=outcome.scores, winner=owner.player_id, loser=loser)
        return updated_outcome, (
            FactionPassiveTriggeredEvent(
                event_id=event_id_start,
                player_id=owner.player_id,
                passive_kind=PassiveKind.NILFGAARD_WINS_TIES,
            ),
        )


class MonstersPassive(FactionPassive):
    @override
    def before_round_cleanup(
        self,
        state: GameState,
        owner: PlayerState,
        *,
        card_registry: CardRegistry,
        rng: SupportsRandom | None,
        event_id_start: int,
    ) -> tuple[frozenset[CardInstanceId], tuple[GameEvent, ...]]:
        monsters_players = tuple(
            player
            for player in state.players
            if passive_kind_for_player(player) == PassiveKind.MONSTERS_KEEP_ONE_UNIT
        )
        if not monsters_players or monsters_players[0].player_id != owner.player_id:
            return frozenset(), ()

        eligible_unit_cards = tuple(
            card.instance_id
            for card in state.card_instances
            if card.zone == Zone.BATTLEFIELD
            and card_registry.get(card.definition_id).card_type == CardType.UNIT
        )
        if not eligible_unit_cards:
            return frozenset(), ()
        if rng is None:
            raise IllegalActionError("Monsters passive requires an injected RNG.")

        retained_card_id = rng.choice(eligible_unit_cards)
        return frozenset({retained_card_id}), (
            FactionPassiveTriggeredEvent(
                event_id=event_id_start,
                player_id=owner.player_id,
                passive_kind=PassiveKind.MONSTERS_KEEP_ONE_UNIT,
                card_instance_id=retained_card_id,
            ),
        )


class NorthernRealmsPassive(FactionPassive):
    @override
    def after_round_winner_finalized(
        self,
        state: GameState,
        owner: PlayerState,
        outcome: RoundOutcome,
        *,
        event_id_start: int,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        if outcome.winner != owner.player_id:
            return state, ()

        drawn_card_ids = drawable_card_ids(owner, 1)
        if not drawn_card_ids:
            return state, ()

        drawn_card_id = drawn_card_ids[0]
        updated_owner = replace(
            owner,
            deck=owner.deck[1:],
            hand=(*owner.hand, drawn_card_id),
        )
        updated_players = replace_player(state.players, updated_owner)
        updated_card = replace(state.card(drawn_card_id), zone=Zone.HAND)
        next_state = replace(
            state,
            players=updated_players,
            card_instances=replace_card_instance(state.card_instances, updated_card),
            event_counter=state.event_counter + 2,
        )
        return next_state, (
            FactionPassiveTriggeredEvent(
                event_id=event_id_start,
                player_id=owner.player_id,
                passive_kind=PassiveKind.NORTHERN_REALMS_DRAW_ON_ROUND_WIN,
            ),
            CardsDrawnEvent(
                event_id=event_id_start + 1,
                player_id=owner.player_id,
                card_instance_ids=(drawn_card_id,),
            ),
        )


class SkelligePassive(FactionPassive):
    @override
    def on_round_start(
        self,
        state: GameState,
        owner: PlayerState,
        *,
        card_registry: CardRegistry,
        rng: SupportsRandom | None,
        event_id_start: int,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        if state.round_number != 3:
            return state, ()

        eligible_card_ids = tuple(
            card_id
            for card_id in owner.discard
            if card_registry.get(state.card(card_id).definition_id).card_type == CardType.UNIT
        )
        if not eligible_card_ids:
            return state, ()
        if rng is None:
            raise IllegalActionError("Skellige passive requires an injected RNG.")

        selected_card_ids = pick_random_card_ids(
            eligible_card_ids,
            rng=rng,
            count=2,
        )
        if not selected_card_ids:
            return state, ()

        updated_rows = owner.rows
        updated_cards: dict[CardInstanceId, CardInstance] = {}
        for card_id in selected_card_ids:
            card = state.card(card_id)
            definition = card_registry.get(card.definition_id)
            target_row = definition.allowed_rows[0]
            updated_rows = append_to_row(updated_rows, target_row, card_id)
            updated_cards[card_id] = replace(
                card,
                zone=Zone.BATTLEFIELD,
                row=target_row,
                battlefield_side=owner.player_id,
            )

        updated_owner = replace(
            owner,
            discard=tuple(card_id for card_id in owner.discard if card_id not in updated_cards),
            rows=updated_rows,
        )
        next_state = replace(
            state,
            players=replace_player(state.players, updated_owner),
            card_instances=replace_card_instances(state.card_instances, updated_cards),
            event_counter=state.event_counter + len(selected_card_ids),
        )
        return next_state, tuple(
            FactionPassiveTriggeredEvent(
                event_id=event_id_start + index,
                player_id=owner.player_id,
                passive_kind=PassiveKind.SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE,
                card_instance_id=card_id,
            )
            for index, card_id in enumerate(selected_card_ids)
        )


PASSIVES_BY_KIND = {
    PassiveKind.MONSTERS_KEEP_ONE_UNIT: MonstersPassive(),
    PassiveKind.NILFGAARD_WINS_TIES: NilfgaardPassive(),
    PassiveKind.NORTHERN_REALMS_DRAW_ON_ROUND_WIN: NorthernRealmsPassive(),
    PassiveKind.SCOIATAEL_CHOOSES_STARTING_PLAYER: ScoiataelPassive(),
    PassiveKind.SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE: SkelligePassive(),
}
DEFAULT_PASSIVE = FactionPassive()


def resolve_starting_player_choice(
    state: GameState,
    requested_starting_player: PlayerId,
) -> tuple[PlayerId, tuple[GameEvent, ...]]:
    chosen_player = requested_starting_player
    events: list[GameEvent] = []
    next_event_id = state.event_counter + 1
    for player in state.players:
        chosen_player, passive_events = passive_for_player(player).choose_starting_player(
            state,
            player,
            chosen_player,
            event_id_start=next_event_id,
        )
        events.extend(passive_events)
        next_event_id += len(passive_events)
    return chosen_player, tuple(events)


def resolve_round_outcome_modifiers(
    state: GameState,
    outcome: RoundOutcome,
) -> tuple[RoundOutcome, tuple[GameEvent, ...]]:
    modified_outcome = outcome
    events: list[GameEvent] = []
    next_event_id = state.event_counter + 1
    for player in state.players:
        modified_outcome, passive_events = passive_for_player(player).modify_round_outcome(
            state,
            player,
            modified_outcome,
            event_id_start=next_event_id,
        )
        events.extend(passive_events)
        next_event_id += len(passive_events)
    return modified_outcome, tuple(events)


def resolve_before_round_cleanup(
    state: GameState,
    *,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> tuple[frozenset[CardInstanceId], tuple[GameEvent, ...]]:
    retained_card_ids: frozenset[CardInstanceId] = frozenset()
    events: list[GameEvent] = []
    next_event_id = state.event_counter + 1
    for player in state.players:
        player_retained_cards, passive_events = passive_for_player(player).before_round_cleanup(
            state,
            player,
            card_registry=card_registry,
            rng=rng,
            event_id_start=next_event_id,
        )
        retained_card_ids = frozenset((*retained_card_ids, *player_retained_cards))
        events.extend(passive_events)
        next_event_id += len(passive_events)
    return retained_card_ids, tuple(events)


def resolve_after_round_winner_finalized(
    state: GameState,
    outcome: RoundOutcome,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    current_state = state
    events: list[GameEvent] = []
    for player in state.players:
        owner = current_state.player(player.player_id)
        current_state, passive_events = passive_for_player(owner).after_round_winner_finalized(
            current_state,
            owner,
            outcome,
            event_id_start=current_state.event_counter + 1,
        )
        events.extend(passive_events)
    return current_state, tuple(events)


def resolve_round_start_passives(
    state: GameState,
    *,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    current_state = state
    events: list[GameEvent] = []
    for player in state.players:
        owner = current_state.player(player.player_id)
        current_state, passive_events = passive_for_player(owner).on_round_start(
            current_state,
            owner,
            card_registry=card_registry,
            rng=rng,
            event_id_start=current_state.event_counter + 1,
        )
        events.extend(passive_events)
    return current_state, tuple(events)


def passive_kind_for_player(player: PlayerState) -> PassiveKind | None:
    return PASSIVE_KIND_BY_FACTION.get(player.faction)


def passive_for_player(player: PlayerState) -> FactionPassive:
    passive_kind = passive_kind_for_player(player)
    if passive_kind is None:
        return DEFAULT_PASSIVE
    return PASSIVES_BY_KIND[passive_kind]
