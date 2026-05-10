from dataclasses import dataclass, replace

from gwent_engine.cards import DeckDefinition
from gwent_engine.core import GameStatus, Phase, Zone
from gwent_engine.core.actions import ResolveMulligansAction, StartGameAction
from gwent_engine.core.config import OPENING_HAND_SIZE
from gwent_engine.core.events import (
    CardsDrawnEvent,
    GameEvent,
    GameStartedEvent,
    MulliganPerformedEvent,
    StartingPlayerChosenEvent,
)
from gwent_engine.core.ids import CardInstanceId, GameId, PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import CardInstance, GameState, LeaderState, PlayerState, RowState
from gwent_engine.factions.passives import resolve_starting_player_choice
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.leader_abilities import resolve_setup_passive_leader_effects
from gwent_engine.rules.state_ops import replace_card_instances


@dataclass(frozen=True, slots=True)
class PlayerDeck:
    player_id: PlayerId
    deck: DeckDefinition


def build_game_state(
    game_id: GameId,
    player_decks: tuple[PlayerDeck, PlayerDeck],
    *,
    rng_seed: int | None = None,
) -> GameState:
    first_player_deck, second_player_deck = player_decks
    first_player_state, first_player_cards = _build_player_state(first_player_deck)
    second_player_state, second_player_cards = _build_player_state(second_player_deck)

    return GameState(
        game_id=game_id,
        players=(first_player_state, second_player_state),
        card_instances=first_player_cards + second_player_cards,
        phase=Phase.NOT_STARTED,
        status=GameStatus.NOT_STARTED,
        rng_seed=rng_seed,
    )


def apply_start_game(
    state: GameState,
    action: StartGameAction,
    *,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    assert rng is not None

    chosen_starting_player, passive_events = resolve_starting_player_choice(
        state,
        action.starting_player,
    )
    updated_cards: dict[CardInstanceId, CardInstance] = {}
    next_event_id = state.event_counter + len(passive_events) + 1
    first_player, second_player = state.players
    updated_first_player, first_draw_event = _prepare_player_for_opening_hand(
        state,
        first_player,
        rng,
        event_id=next_event_id + 2,
        updated_cards=updated_cards,
    )
    updated_second_player, second_draw_event = _prepare_player_for_opening_hand(
        state,
        second_player,
        rng,
        event_id=next_event_id + 3,
        updated_cards=updated_cards,
    )

    events: tuple[GameEvent, ...] = (
        *passive_events,
        StartingPlayerChosenEvent(event_id=next_event_id, player_id=chosen_starting_player),
        GameStartedEvent(event_id=next_event_id + 1, phase=Phase.MULLIGAN, round_number=1),
        first_draw_event,
        second_draw_event,
    )

    started_state = replace(
        state,
        players=(updated_first_player, updated_second_player),
        card_instances=replace_card_instances(state.card_instances, updated_cards),
        current_player=None,
        starting_player=chosen_starting_player,
        round_starter=chosen_starting_player,
        round_number=1,
        phase=Phase.MULLIGAN,
        status=GameStatus.IN_PROGRESS,
        match_winner=None,
        event_counter=state.event_counter + len(events),
    )
    leader_state, leader_events = resolve_setup_passive_leader_effects(
        started_state,
        leader_registry=leader_registry,
    )
    return leader_state, events + leader_events


def apply_mulligan(
    state: GameState,
    action: ResolveMulligansAction,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    updated_cards: dict[CardInstanceId, CardInstance] = {}
    selections_by_player = {
        selection.player_id: selection.cards_to_replace for selection in action.selections
    }
    updated_players: list[PlayerState] = []
    events: list[GameEvent] = []
    next_event_id = state.event_counter + 1
    for player in state.players:
        replaced_cards = selections_by_player[player.player_id]
        drawn_cards = tuple(player.deck[: len(replaced_cards)])
        replaced_card_ids = set(replaced_cards)
        kept_hand = tuple(card_id for card_id in player.hand if card_id not in replaced_card_ids)
        remaining_deck = tuple(player.deck[len(replaced_cards) :])
        updated_players.append(
            replace(
                player,
                deck=remaining_deck + replaced_cards,
                hand=kept_hand + drawn_cards,
                discard=player.discard,
            )
        )
        for card_id in replaced_cards:
            updated_cards[card_id] = replace(state.card(card_id), zone=Zone.DECK)
        for card_id in drawn_cards:
            updated_cards[card_id] = replace(state.card(card_id), zone=Zone.HAND)
        events.append(
            MulliganPerformedEvent(
                event_id=next_event_id,
                player_id=player.player_id,
                replaced_card_instance_ids=replaced_cards,
                drawn_card_instance_ids=drawn_cards,
            )
        )
        next_event_id += 1

    assert state.starting_player is not None
    next_state = replace(
        state,
        players=(updated_players[0], updated_players[1]),
        card_instances=replace_card_instances(state.card_instances, updated_cards),
        current_player=state.starting_player,
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, tuple(events)


def _build_player_state(
    player_deck: PlayerDeck,
) -> tuple[PlayerState, tuple[CardInstance, ...]]:
    deck_card_ids: list[CardInstanceId] = []
    card_instances: list[CardInstance] = []
    for index, definition_id in enumerate(player_deck.deck.card_definition_ids, start=1):
        instance_id = CardInstanceId(f"{player_deck.player_id}_card_{index}")
        deck_card_ids.append(instance_id)
        card_instances.append(
            CardInstance(
                instance_id=instance_id,
                definition_id=definition_id,
                owner=player_deck.player_id,
                zone=Zone.DECK,
            )
        )

    return (
        PlayerState(
            player_id=player_deck.player_id,
            faction=player_deck.deck.faction,
            leader=LeaderState(leader_id=player_deck.deck.leader_id),
            deck=tuple(deck_card_ids),
            hand=(),
            discard=(),
            rows=RowState(),
        ),
        tuple(card_instances),
    )


def _prepare_player_for_opening_hand(
    state: GameState,
    player: PlayerState,
    rng: SupportsRandom,
    *,
    event_id: int,
    updated_cards: dict[CardInstanceId, CardInstance],
) -> tuple[PlayerState, CardsDrawnEvent]:
    shuffled_deck = list(player.deck)
    rng.shuffle(shuffled_deck)

    opening_hand = tuple(shuffled_deck[:OPENING_HAND_SIZE])
    remaining_deck = tuple(shuffled_deck[OPENING_HAND_SIZE:])
    for card_id in opening_hand:
        updated_cards[card_id] = replace(state.card(card_id), zone=Zone.HAND)

    return (
        replace(
            player,
            deck=remaining_deck,
            hand=opening_hand,
            discard=(),
            rows=RowState(),
            has_passed=False,
        ),
        CardsDrawnEvent(
            event_id=event_id,
            player_id=player.player_id,
            card_instance_ids=opening_hand,
        ),
    )
