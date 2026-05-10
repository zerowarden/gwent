from dataclasses import dataclass

from gwent_engine.core import AbilityKind, CardType, FactionId, Row
from gwent_engine.core.ids import CardDefinitionId, DeckId, LeaderId

_UNIT_ONLY_METADATA_FIELDS: tuple[str, ...] = (
    "musters_group",
    "muster_group",
    "bond_group",
    "transforms_into_definition_id",
    "avenger_summon_definition_id",
)


@dataclass(frozen=True, slots=True)
class CardDefinition:
    definition_id: CardDefinitionId
    name: str
    faction: FactionId
    card_type: CardType
    base_strength: int
    allowed_rows: tuple[Row, ...]
    ability_kinds: tuple[AbilityKind, ...] = ()
    musters_group: str | None = None
    muster_group: str | None = None
    bond_group: str | None = None
    transforms_into_definition_id: CardDefinitionId | None = None
    avenger_summon_definition_id: CardDefinitionId | None = None
    generated_only: bool = False
    max_copies_per_deck: int | None = None
    is_hero: bool = False
    rule_text: str | None = None

    def __post_init__(self) -> None:
        self._validate_common_fields()
        self._validate_card_type_specific_rules()

    def _validate_common_fields(self) -> None:
        if not self.name.strip():
            raise ValueError("CardDefinition name cannot be blank.")
        self._validate_optional_non_blank(
            self.musters_group,
            "CardDefinition musters_group cannot be blank when provided.",
        )
        self._validate_optional_non_blank(
            self.muster_group,
            "CardDefinition muster_group cannot be blank when provided.",
        )
        self._validate_optional_non_blank(
            self.bond_group,
            "CardDefinition bond_group cannot be blank when provided.",
        )
        self._validate_optional_non_blank(
            self.rule_text,
            "CardDefinition rule_text cannot be blank when provided.",
        )
        if self.base_strength < 0:
            raise ValueError("CardDefinition base_strength cannot be negative.")
        if self.max_copies_per_deck is not None and self.max_copies_per_deck < 1:
            raise ValueError("CardDefinition max_copies_per_deck must be at least 1 when provided.")
        self._validate_no_duplicates(
            self.allowed_rows,
            "CardDefinition allowed_rows cannot contain duplicates.",
        )
        self._validate_no_duplicates(
            self.ability_kinds,
            "CardDefinition ability_kinds cannot contain duplicates.",
        )

    def _validate_card_type_specific_rules(self) -> None:
        match self.card_type:
            case CardType.UNIT:
                self._validate_unit_rules()
            case CardType.SPECIAL:
                self._validate_special_rules()
            case _:
                self._validate_leader_rules()

    def _validate_unit_rules(self) -> None:
        if not self.allowed_rows:
            raise ValueError("Unit cards must declare at least one allowed row.")

        self._validate_muster_rules()
        self._validate_ability_bound_metadata(
            AbilityKind.TIGHT_BOND,
            value=self.bond_group,
            required_message="Tight Bond units must declare a bond_group.",
            forbidden_message="Only Tight Bond units may declare a bond_group.",
        )
        self._validate_ability_bound_metadata(
            AbilityKind.BERSERKER,
            value=self.transforms_into_definition_id,
            required_message="Berserker units must declare transforms_into_definition_id.",
            forbidden_message="Only Berserker units may declare transforms_into_definition_id.",
        )
        self._validate_ability_bound_metadata(
            AbilityKind.AVENGER,
            value=self.avenger_summon_definition_id,
            required_message="Avenger units must declare avenger_summon_definition_id.",
            forbidden_message="Only Avenger units may declare avenger_summon_definition_id.",
        )

    def _validate_muster_rules(self) -> None:
        if self._has_ability(AbilityKind.MUSTER):
            self._require_any_muster_group()
            return
        if self.musters_group is not None:
            raise ValueError("Only Muster units may declare a musters_group.")

    def _require_any_muster_group(self) -> None:
        if self.musters_group is None and self.muster_group is None:
            raise ValueError("Muster units must declare a musters_group or muster_group.")

    def _validate_special_rules(self) -> None:
        if self.base_strength != 0:
            raise ValueError("Special cards must not carry base strength.")
        if self.is_hero:
            raise ValueError("Only unit cards may be marked as heroes.")
        self._require_no_unit_only_metadata("Special cards cannot declare unit metadata.")
        if len(self.ability_kinds) != 1:
            raise ValueError("Special cards must declare exactly one ability_kind.")

        special_ability = self.ability_kinds[0]
        if self._is_row_targeted_special(special_ability):
            self._require(
                bool(self.allowed_rows),
                "Row-targeted special cards must declare at least one allowed row.",
            )
            return

        if self.allowed_rows:
            raise ValueError(
                "Only row-targeted special cards may declare allowed_rows in the current scope."
            )

    def _validate_leader_rules(self) -> None:
        if self.base_strength != 0:
            raise ValueError("Only unit cards may carry base strength in the current scope.")
        if self.is_hero:
            raise ValueError("Only unit cards may be marked as heroes.")
        if self.allowed_rows:
            raise ValueError(
                "Only unit or horn cards may declare allowed_rows in the current scope."
            )
        self._require_no_unit_only_metadata("Only unit cards may declare unit metadata.")

    def _validate_ability_bound_metadata(
        self,
        ability_kind: AbilityKind,
        *,
        value: object | None,
        required_message: str,
        forbidden_message: str,
    ) -> None:
        if self._has_ability(ability_kind):
            self._require_present(value, required_message)
            return
        if value is not None:
            raise ValueError(forbidden_message)

    def _has_ability(self, ability_kind: AbilityKind) -> bool:
        return ability_kind in self.ability_kinds

    @staticmethod
    def _is_row_targeted_special(ability_kind: AbilityKind) -> bool:
        return ability_kind in (AbilityKind.COMMANDERS_HORN, AbilityKind.MARDROEME)

    @staticmethod
    def _require_present(value: object | None, message: str) -> None:
        if value is None:
            raise ValueError(message)

    def _require_no_unit_only_metadata(self, message: str) -> None:
        self._require(
            not any(
                getattr(self, field_name) is not None for field_name in _UNIT_ONLY_METADATA_FIELDS
            ),
            message,
        )

    @staticmethod
    def _require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    @staticmethod
    def _validate_optional_non_blank(
        value: str | None,
        message: str,
    ) -> None:
        if value is not None and not value.strip():
            raise ValueError(message)

    @staticmethod
    def _validate_no_duplicates(values: tuple[object, ...], message: str) -> None:
        if len(set(values)) != len(values):
            raise ValueError(message)

    def effective_max_copies_per_deck(self) -> int:
        return 1 if self.max_copies_per_deck is None else self.max_copies_per_deck

    @property
    def resolved_musters_group(self) -> str | None:
        if AbilityKind.MUSTER not in self.ability_kinds:
            return None
        return self.musters_group or self.muster_group


@dataclass(frozen=True, slots=True)
class DeckDefinition:
    deck_id: DeckId
    faction: FactionId
    leader_id: LeaderId
    card_definition_ids: tuple[CardDefinitionId, ...]

    def __post_init__(self) -> None:
        if not self.card_definition_ids:
            raise ValueError("DeckDefinition must contain at least one card definition id.")
