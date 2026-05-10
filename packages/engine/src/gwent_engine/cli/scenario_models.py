from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.core import FactionId, Row
from gwent_engine.core.ids import CardDefinitionId, DeckId, GameId, LeaderId, PlayerId


@dataclass(frozen=True, slots=True)
class ScenarioRng:
    shuffle: str = "identity"
    choice: str = "first"
    choice_index: int = 0


@dataclass(frozen=True, slots=True)
class ScenarioDeckEntry:
    alias: str
    card_definition_id: CardDefinitionId


@dataclass(frozen=True, slots=True)
class ScenarioPlayer:
    player_id: PlayerId
    deck_id: DeckId
    faction: FactionId
    leader_id: LeaderId
    deck_entries: tuple[ScenarioDeckEntry, ...]


@dataclass(frozen=True, slots=True)
class ScenarioStartGameStep:
    starting_player: PlayerId | None = None


@dataclass(frozen=True, slots=True)
class ScenarioMulliganStep:
    selections: dict[PlayerId, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ScenarioPlayCardStep:
    player_id: PlayerId
    card_ref: str
    target_row: Row | None = None
    target_card_ref: str | None = None
    secondary_target_card_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioPassStep:
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class ScenarioLeaveStep:
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class ScenarioUseLeaderAbilityStep:
    player_id: PlayerId
    target_row: Row | None = None
    target_player: PlayerId | None = None
    target_card_ref: str | None = None
    secondary_target_card_ref: str | None = None
    selected_card_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioResolveChoiceStep:
    player_id: PlayerId
    selected_card_refs: tuple[str, ...] = ()
    selected_rows: tuple[Row, ...] = ()


type ScenarioStep = (
    ScenarioStartGameStep
    | ScenarioMulliganStep
    | ScenarioPlayCardStep
    | ScenarioPassStep
    | ScenarioLeaveStep
    | ScenarioUseLeaderAbilityStep
    | ScenarioResolveChoiceStep
)


@dataclass(frozen=True, slots=True)
class CliScenario:
    scenario_id: str
    game_id: GameId
    starting_player: PlayerId
    rng: ScenarioRng
    players: tuple[ScenarioPlayer, ScenarioPlayer]
    steps: tuple[ScenarioStep, ...]
