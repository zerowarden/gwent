from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from gwent_engine.core.actions import GameAction
from gwent_engine.core.events import GameEvent
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState

type PlayerActionKind = Literal["pass", "leave"]


@dataclass(frozen=True, slots=True)
class EnginePlayerDeckSpec:
    player_id: str
    deck_id: str


@dataclass(frozen=True, slots=True)
class CreateMatchStateSpec:
    game_id: str
    players: tuple[EnginePlayerDeckSpec, EnginePlayerDeckSpec]
    rng_seed: int | None = None


@dataclass(frozen=True, slots=True)
class EngineTransitionResult:
    next_state: GameState
    events: tuple[GameEvent, ...]


@dataclass(frozen=True, slots=True)
class CardCatalogEntry:
    definition_id: str
    name: str
    faction: str
    card_type: str
    is_hero: bool


@dataclass(frozen=True, slots=True)
class LeaderCatalogEntry:
    leader_id: str
    name: str
    faction: str


class EngineAdapter(Protocol):
    def create_match_state(self, spec: CreateMatchStateSpec) -> GameState: ...

    def build_start_game_action(self, *, starting_player_id: str) -> GameAction: ...

    def build_resolve_mulligans_action(
        self,
        *,
        player_order: Sequence[str],
        selections_by_player_id: Mapping[str, tuple[str, ...]],
    ) -> GameAction: ...

    def build_play_card_action(
        self,
        *,
        player_id: str,
        card_instance_id: str,
        target_row: str | None = None,
        target_card_instance_id: str | None = None,
        secondary_target_card_instance_id: str | None = None,
    ) -> GameAction: ...

    def build_player_action(self, *, kind: PlayerActionKind, player_id: str) -> GameAction: ...

    def build_use_leader_ability_action(
        self,
        *,
        player_id: str,
        target_row: str | None = None,
        target_player: str | None = None,
        target_card_instance_id: str | None = None,
        secondary_target_card_instance_id: str | None = None,
        selected_card_instance_ids: tuple[str, ...] = (),
    ) -> GameAction: ...

    def build_resolve_choice_action(
        self,
        *,
        player_id: str,
        choice_id: str,
        selected_card_instance_ids: tuple[str, ...] = (),
        selected_rows: tuple[str, ...] = (),
    ) -> GameAction: ...

    def apply_engine_action(
        self,
        state: GameState,
        action: GameAction,
        *,
        rng: SupportsRandom | None = None,
    ) -> EngineTransitionResult: ...

    def serialize_state(self, state: GameState) -> dict[str, object]: ...

    def deserialize_state(self, payload: Mapping[str, object]) -> GameState: ...

    def serialize_events(self, events: Sequence[GameEvent]) -> tuple[dict[str, object], ...]: ...

    def deserialize_events(
        self,
        payloads: Sequence[Mapping[str, object]],
    ) -> tuple[GameEvent, ...]: ...

    def get_card_entry(self, definition_id: str) -> CardCatalogEntry: ...

    def get_leader_entry(self, leader_id: str) -> LeaderCatalogEntry: ...
