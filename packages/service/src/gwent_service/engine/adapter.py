from __future__ import annotations

from collections.abc import Mapping, Sequence

from gwent_engine.cards import (
    CardRegistry,
    DeckDefinition,
    load_card_definitions,
)
from gwent_engine.core import Row
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.events import GameEvent
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import GameState
from gwent_engine.decks import load_sample_decks
from gwent_engine.leaders import LeaderRegistry, load_leader_definitions
from gwent_engine.rules.game_setup import PlayerDeck, build_game_state
from gwent_engine.serialize import (
    events_to_dict,
    game_state_from_dict,
    game_state_to_dict,
)
from gwent_shared.error_translation import translate_exception

from gwent_service.config import ServiceConfig, default_service_config
from gwent_service.engine.contracts import (
    CardCatalogEntry,
    CreateMatchStateSpec,
    EnginePlayerDeckSpec,
    EngineTransitionResult,
    LeaderCatalogEntry,
    PlayerActionKind,
)
from gwent_service.engine.randomness import StdlibRandomAdapter


class GwentEngineAdapter:
    def __init__(self, config: ServiceConfig | None = None) -> None:
        self._config: ServiceConfig = config or default_service_config()
        self._card_registry: CardRegistry = CardRegistry.from_definitions(
            load_card_definitions(self._config.cards_path)
        )
        self._leader_registry: LeaderRegistry = LeaderRegistry.from_definitions(
            load_leader_definitions(self._config.leaders_path)
        )
        self._decks_by_id: dict[str, DeckDefinition] = {
            str(deck.deck_id): deck
            for deck in load_sample_decks(
                self._config.sample_decks_path,
                self._card_registry,
                self._leader_registry,
            )
        }

    def create_match_state(self, spec: CreateMatchStateSpec) -> GameState:
        if len(spec.players) != 2:
            raise ValueError("CreateMatchStateSpec requires exactly two players.")
        player_ids = {player.player_id for player in spec.players}
        if len(player_ids) != len(spec.players):
            raise ValueError("CreateMatchStateSpec player ids must be unique.")

        first_player, second_player = spec.players
        return build_game_state(
            game_id=GameId(spec.game_id),
            player_decks=(
                self._build_player_deck(first_player),
                self._build_player_deck(second_player),
            ),
            rng_seed=spec.rng_seed,
        )

    def build_start_game_action(self, *, starting_player_id: str) -> GameAction:
        return StartGameAction(starting_player=PlayerId(starting_player_id))

    def build_resolve_mulligans_action(
        self,
        *,
        player_order: Sequence[str],
        selections_by_player_id: Mapping[str, tuple[str, ...]],
    ) -> GameAction:
        return ResolveMulligansAction(
            selections=tuple(
                MulliganSelection(
                    player_id=PlayerId(player_id),
                    cards_to_replace=tuple(
                        CardInstanceId(card_instance_id)
                        for card_instance_id in selections_by_player_id[player_id]
                    ),
                )
                for player_id in player_order
            )
        )

    def build_play_card_action(
        self,
        *,
        player_id: str,
        card_instance_id: str,
        target_row: str | None = None,
        target_card_instance_id: str | None = None,
        secondary_target_card_instance_id: str | None = None,
    ) -> GameAction:
        return PlayCardAction(
            player_id=PlayerId(player_id),
            card_instance_id=CardInstanceId(card_instance_id),
            target_row=_optional_row(target_row),
            target_card_instance_id=_optional_card_instance_id(target_card_instance_id),
            secondary_target_card_instance_id=_optional_card_instance_id(
                secondary_target_card_instance_id
            ),
        )

    def build_player_action(self, *, kind: PlayerActionKind, player_id: str) -> GameAction:
        player = PlayerId(player_id)
        match kind:
            case "pass":
                return PassAction(player_id=player)
            case "leave":
                return LeaveAction(player_id=player)

    def build_use_leader_ability_action(
        self,
        *,
        player_id: str,
        target_row: str | None = None,
        target_player: str | None = None,
        target_card_instance_id: str | None = None,
        secondary_target_card_instance_id: str | None = None,
        selected_card_instance_ids: tuple[str, ...] = (),
    ) -> GameAction:
        return UseLeaderAbilityAction(
            player_id=PlayerId(player_id),
            target_row=_optional_row(target_row),
            target_player=PlayerId(target_player) if target_player is not None else None,
            target_card_instance_id=_optional_card_instance_id(target_card_instance_id),
            secondary_target_card_instance_id=_optional_card_instance_id(
                secondary_target_card_instance_id
            ),
            selected_card_instance_ids=tuple(
                CardInstanceId(card_instance_id) for card_instance_id in selected_card_instance_ids
            ),
        )

    def build_resolve_choice_action(
        self,
        *,
        player_id: str,
        choice_id: str,
        selected_card_instance_ids: tuple[str, ...] = (),
        selected_rows: tuple[str, ...] = (),
    ) -> GameAction:
        return ResolveChoiceAction(
            player_id=PlayerId(player_id),
            choice_id=ChoiceId(choice_id),
            selected_card_instance_ids=tuple(
                CardInstanceId(card_instance_id) for card_instance_id in selected_card_instance_ids
            ),
            selected_rows=tuple(Row(row) for row in selected_rows),
        )

    def apply_engine_action(
        self,
        state: GameState,
        action: GameAction,
        *,
        rng: SupportsRandom | None = None,
    ) -> EngineTransitionResult:
        resolved_rng = rng if rng is not None else StdlibRandomAdapter()
        next_state, events = apply_action(
            state,
            action,
            rng=resolved_rng,
            card_registry=self._card_registry,
            leader_registry=self._leader_registry,
        )
        return EngineTransitionResult(next_state=next_state, events=events)

    def serialize_state(self, state: GameState) -> dict[str, object]:
        return game_state_to_dict(state)

    def deserialize_state(self, payload: Mapping[str, object]) -> GameState:
        return game_state_from_dict(payload)

    def serialize_events(self, events: Sequence[GameEvent]) -> tuple[dict[str, object], ...]:
        return tuple(events_to_dict(events))

    def get_card_entry(self, definition_id: str) -> CardCatalogEntry:
        definition = self._card_registry.get(CardDefinitionId(definition_id))
        return CardCatalogEntry(
            definition_id=str(definition.definition_id),
            name=definition.name,
            faction=definition.faction.value,
            card_type=definition.card_type.value,
            is_hero=definition.is_hero,
        )

    def get_leader_entry(self, leader_id: str) -> LeaderCatalogEntry:
        definition = self._leader_registry.get(LeaderId(leader_id))
        return LeaderCatalogEntry(
            leader_id=str(definition.leader_id),
            name=definition.name,
            faction=definition.faction.value,
        )

    def _build_player_deck(self, player_spec: EnginePlayerDeckSpec) -> PlayerDeck:
        deck = translate_exception(
            lambda: self._decks_by_id[player_spec.deck_id],
            KeyError,
            lambda _exc: ValueError(f"Unknown sample deck id: {player_spec.deck_id!r}"),
        )
        return PlayerDeck(
            player_id=PlayerId(player_spec.player_id),
            deck=deck,
        )


def _optional_card_instance_id(raw_value: str | None) -> CardInstanceId | None:
    if raw_value is None:
        return None
    return CardInstanceId(raw_value)


def _optional_row(raw_value: str | None) -> Row | None:
    if raw_value is None:
        return None
    return Row(raw_value)
