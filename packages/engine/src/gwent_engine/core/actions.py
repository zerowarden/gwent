from dataclasses import dataclass

from gwent_engine.core.enums import Row
from gwent_engine.core.ids import CardInstanceId, ChoiceId, PlayerId


@dataclass(frozen=True, slots=True)
class StartGameAction:
    starting_player: PlayerId


@dataclass(frozen=True, slots=True)
class MulliganSelection:
    player_id: PlayerId
    cards_to_replace: tuple[CardInstanceId, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolveMulligansAction:
    selections: tuple[MulliganSelection, ...]


@dataclass(frozen=True, slots=True)
class PlayCardAction:
    player_id: PlayerId
    card_instance_id: CardInstanceId
    target_row: Row | None = None
    target_card_instance_id: CardInstanceId | None = None
    secondary_target_card_instance_id: CardInstanceId | None = None


@dataclass(frozen=True, slots=True)
class PassAction:
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class LeaveAction:
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class ResolveChoiceAction:
    player_id: PlayerId
    choice_id: ChoiceId
    selected_card_instance_ids: tuple[CardInstanceId, ...] = ()
    selected_rows: tuple[Row, ...] = ()


@dataclass(frozen=True, slots=True)
class UseLeaderAbilityAction:
    player_id: PlayerId
    target_row: Row | None = None
    target_player: PlayerId | None = None
    target_card_instance_id: CardInstanceId | None = None
    secondary_target_card_instance_id: CardInstanceId | None = None
    selected_card_instance_ids: tuple[CardInstanceId, ...] = ()


type GameAction = (
    StartGameAction
    | ResolveMulligansAction
    | PlayCardAction
    | PassAction
    | LeaveAction
    | ResolveChoiceAction
    | UseLeaderAbilityAction
)
