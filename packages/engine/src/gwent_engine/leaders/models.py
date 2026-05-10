from collections.abc import Callable
from dataclasses import dataclass

from gwent_engine.core import (
    WEATHER_ABILITY_KINDS,
    AbilityKind,
    FactionId,
    LeaderAbilityKind,
    LeaderAbilityMode,
    LeaderSelectionMode,
    Row,
)
from gwent_engine.core.ids import LeaderId


@dataclass(frozen=True, slots=True)
class LeaderDefinition:
    leader_id: LeaderId
    name: str
    faction: FactionId
    ability_kind: LeaderAbilityKind
    ability_mode: LeaderAbilityMode
    uses_per_match: int = 1
    selection_mode: LeaderSelectionMode | None = None
    weather_ability_kind: AbilityKind | None = None
    affected_row: Row | None = None
    blocked_if_row_already_affected_by_horn: bool = False
    minimum_opponent_row_total: int = 0
    cards_to_draw: int = 0
    hand_discard_count: int = 0
    deck_pick_count: int = 0
    reveal_count: int = 0
    rule_text: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("LeaderDefinition name cannot be blank.")
        _require_non_negative(self.uses_per_match, "uses_per_match")
        _require_non_negative(self.cards_to_draw, "cards_to_draw")
        _require_non_negative(self.hand_discard_count, "hand_discard_count")
        _require_non_negative(self.deck_pick_count, "deck_pick_count")
        _require_non_negative(self.reveal_count, "reveal_count")
        _require_non_negative(self.minimum_opponent_row_total, "minimum_opponent_row_total")

        validator = _ABILITY_VALIDATORS.get(self.ability_kind)
        if validator is None:
            raise ValueError(f"Unsupported leader ability kind: {self.ability_kind!r}")
        validator(self)


type LeaderDefinitionValidator = Callable[[LeaderDefinition], None]


def _require_non_negative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"LeaderDefinition {field_name} cannot be negative.")


def _require_mode(
    definition: LeaderDefinition,
    expected_mode: LeaderAbilityMode,
) -> None:
    if definition.ability_mode != expected_mode:
        raise ValueError(f"{definition.ability_kind.name} leaders must be {expected_mode.value}.")


def _require_affected_row(definition: LeaderDefinition) -> None:
    if definition.affected_row is None:
        raise ValueError(f"{definition.ability_kind.name} leaders must declare an affected_row.")


def _validate_active_leader(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)


def _validate_passive_leader(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.PASSIVE)


def _validate_clear_weather(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)
    if (
        definition.weather_ability_kind is not None
        or definition.affected_row is not None
        or definition.selection_mode is not None
    ):
        raise ValueError("CLEAR_WEATHER leaders do not declare extra parameters.")


def _validate_play_weather_from_deck(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)
    if definition.selection_mode not in (
        LeaderSelectionMode.SPECIFIC,
        LeaderSelectionMode.CHOOSE,
    ):
        raise ValueError("PLAY_WEATHER_FROM_DECK leaders must declare a specific or choose mode.")
    if (
        definition.selection_mode == LeaderSelectionMode.SPECIFIC
        and definition.weather_ability_kind not in WEATHER_ABILITY_KINDS
    ):
        raise ValueError("PLAY_WEATHER_FROM_DECK leaders in specific mode must declare a weather.")
    if (
        definition.selection_mode == LeaderSelectionMode.CHOOSE
        and definition.weather_ability_kind is not None
    ):
        raise ValueError("PLAY_WEATHER_FROM_DECK leaders in choose mode must not pin one weather.")
    if definition.affected_row is not None or definition.cards_to_draw or definition.reveal_count:
        raise ValueError("PLAY_WEATHER_FROM_DECK leaders do not use row/draw/reveal data.")


def _validate_horn_own_row(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)
    _require_affected_row(definition)


def _validate_scorch_opponent_row(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)
    _require_affected_row(definition)
    if definition.minimum_opponent_row_total < 1:
        raise ValueError(
            "SCORCH_OPPONENT_ROW leaders must declare minimum_opponent_row_total >= 1."
        )


def _validate_discard_and_choose_from_deck(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)
    if definition.hand_discard_count < 1 or definition.deck_pick_count < 1:
        raise ValueError(
            "DISCARD_AND_CHOOSE_FROM_DECK leaders require positive discard and pick counts."
        )


def _validate_reveal_random_opponent_hand_cards(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.ACTIVE)
    if definition.reveal_count < 1:
        raise ValueError(
            "REVEAL_RANDOM_OPPONENT_HAND_CARDS leaders must declare reveal_count >= 1."
        )


def _validate_draw_extra_opening_card(definition: LeaderDefinition) -> None:
    _require_mode(definition, LeaderAbilityMode.PASSIVE)
    if definition.cards_to_draw < 1:
        raise ValueError("DRAW_EXTRA_OPENING_CARD leaders must declare cards_to_draw >= 1.")
    if definition.weather_ability_kind is not None or definition.affected_row is not None:
        raise ValueError("DRAW_EXTRA_OPENING_CARD leaders do not use weather or row parameters.")


_ABILITY_VALIDATORS: dict[LeaderAbilityKind, LeaderDefinitionValidator] = {
    LeaderAbilityKind.CLEAR_WEATHER: _validate_clear_weather,
    LeaderAbilityKind.PLAY_WEATHER_FROM_DECK: _validate_play_weather_from_deck,
    LeaderAbilityKind.HORN_OWN_ROW: _validate_horn_own_row,
    LeaderAbilityKind.SCORCH_OPPONENT_ROW: _validate_scorch_opponent_row,
    LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK: _validate_discard_and_choose_from_deck,
    LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND: _validate_active_leader,
    LeaderAbilityKind.DOUBLE_SPY_STRENGTH_GLOBAL: _validate_passive_leader,
    LeaderAbilityKind.REVEAL_RANDOM_OPPONENT_HAND_CARDS: (
        _validate_reveal_random_opponent_hand_cards
    ),
    LeaderAbilityKind.DISABLE_OPPONENT_LEADER: _validate_passive_leader,
    LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND: _validate_active_leader,
    LeaderAbilityKind.RANDOMIZE_RESTORE_TO_BATTLEFIELD_SELECTION: _validate_passive_leader,
    LeaderAbilityKind.DRAW_EXTRA_OPENING_CARD: _validate_draw_extra_opening_card,
    LeaderAbilityKind.OPTIMIZE_AGILE_ROWS: _validate_active_leader,
    LeaderAbilityKind.SHUFFLE_ALL_DISCARDS_INTO_DECKS: _validate_active_leader,
    LeaderAbilityKind.HALVE_WEATHER_PENALTY: _validate_passive_leader,
}
