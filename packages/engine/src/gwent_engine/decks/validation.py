from collections import Counter
from dataclasses import dataclass

from gwent_engine.cards import CardDefinition, CardRegistry, DeckDefinition
from gwent_engine.core import CardType, FactionId
from gwent_engine.core.ids import CardDefinitionId
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry


@dataclass(frozen=True, slots=True)
class DeckValidationError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DeckValidationResult:
    errors: tuple[DeckValidationError, ...]


@dataclass(frozen=True, slots=True)
class DeckRuleset:
    min_unit_cards: int = 22
    max_special_cards: int = 10
    require_single_leader: bool = True
    enforce_faction: bool = True


DEFAULT_DECK_RULESET = DeckRuleset()


@dataclass(frozen=True, slots=True)
class _DeckCardScan:
    unit_count: int
    special_count: int
    embedded_leader_count: int
    known_card_ids: tuple[CardDefinitionId, ...]
    malformed_card_ids: tuple[CardDefinitionId, ...]
    unknown_card_ids: tuple[CardDefinitionId, ...]
    off_faction_card_ids: tuple[CardDefinitionId, ...]


def validate_deck(
    deck: DeckDefinition,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    ruleset: DeckRuleset = DEFAULT_DECK_RULESET,
) -> DeckValidationResult:
    errors: list[DeckValidationError] = []
    leader_definition = _leader_definition(deck, leader_registry, errors)
    scan = _scan_deck_cards(
        deck,
        card_registry,
        leader_definition=leader_definition,
        ruleset=ruleset,
    )
    errors.extend(_validate_deck_shape(deck))
    errors.extend(_scan_errors(scan))
    errors.extend(_validate_copy_limits(scan.known_card_ids, card_registry))
    errors.extend(_ruleset_errors(deck, scan, leader_definition=leader_definition, ruleset=ruleset))
    return DeckValidationResult(errors=tuple(errors))


def _validate_deck_shape(deck: DeckDefinition) -> tuple[DeckValidationError, ...]:
    errors: list[DeckValidationError] = []
    if not str(deck.deck_id).strip():
        errors.append(_error("malformed_deck", "Deck id cannot be blank."))
    if not deck.card_definition_ids:
        errors.append(
            _error(
                "malformed_deck",
                "Deck must include at least one card definition id.",
            )
        )
    return tuple(errors)


def _leader_definition(
    deck: DeckDefinition,
    leader_registry: LeaderRegistry,
    errors: list[DeckValidationError],
) -> LeaderDefinition | None:
    if not str(deck.leader_id).strip():
        errors.append(_error("missing_leader", "Deck must declare exactly one leader."))
        return None
    if deck.leader_id not in leader_registry:
        errors.append(_error("unknown_leader", f"Unknown leader id {deck.leader_id!r}."))
        return None
    return leader_registry.get(deck.leader_id)


def _scan_deck_cards(
    deck: DeckDefinition,
    card_registry: CardRegistry,
    *,
    leader_definition: LeaderDefinition | None,
    ruleset: DeckRuleset,
) -> _DeckCardScan:
    unit_count = 0
    special_count = 0
    embedded_leader_count = 0
    unknown_card_ids: list[CardDefinitionId] = []
    off_faction_card_ids: list[CardDefinitionId] = []
    malformed_card_ids: list[CardDefinitionId] = []
    known_card_ids: list[CardDefinitionId] = []

    for definition_id in deck.card_definition_ids:
        if not str(definition_id).strip():
            malformed_card_ids.append(definition_id)
            continue
        if definition_id not in card_registry:
            unknown_card_ids.append(definition_id)
            continue

        definition = card_registry.get(definition_id)
        known_card_ids.append(definition_id)
        unit_count += int(definition.card_type == CardType.UNIT)
        special_count += int(definition.card_type == CardType.SPECIAL)
        embedded_leader_count += int(definition.card_type == CardType.LEADER)
        if _is_off_faction_card(definition, leader_definition=leader_definition, ruleset=ruleset):
            off_faction_card_ids.append(definition_id)

    return _DeckCardScan(
        unit_count=unit_count,
        special_count=special_count,
        embedded_leader_count=embedded_leader_count,
        known_card_ids=tuple(known_card_ids),
        malformed_card_ids=tuple(malformed_card_ids),
        unknown_card_ids=tuple(unknown_card_ids),
        off_faction_card_ids=tuple(off_faction_card_ids),
    )


def _is_off_faction_card(
    definition: CardDefinition,
    *,
    leader_definition: LeaderDefinition | None,
    ruleset: DeckRuleset,
) -> bool:
    if not ruleset.enforce_faction or leader_definition is None:
        return False
    if definition.card_type == CardType.LEADER:
        return False
    return definition.faction not in (leader_definition.faction, FactionId.NEUTRAL)


def _scan_errors(scan: _DeckCardScan) -> tuple[DeckValidationError, ...]:
    errors: list[DeckValidationError] = []
    if scan.malformed_card_ids:
        ids = _joined_ids(scan.malformed_card_ids)
        errors.append(
            _error(
                "malformed_deck",
                f"Deck contains malformed card definition ids: {ids}.",
            )
        )
    if scan.unknown_card_ids:
        ids = _joined_ids(scan.unknown_card_ids)
        errors.append(
            _error(
                "unknown_card_definition",
                f"Deck references unknown card definition ids: {ids}.",
            )
        )
    return tuple(errors)


def _ruleset_errors(
    deck: DeckDefinition,
    scan: _DeckCardScan,
    *,
    leader_definition: LeaderDefinition | None,
    ruleset: DeckRuleset,
) -> tuple[DeckValidationError, ...]:
    errors: list[DeckValidationError] = []
    errors.extend(_leader_count_errors(deck, scan, ruleset=ruleset))
    errors.extend(_composition_errors(scan, ruleset=ruleset))
    errors.extend(
        _faction_errors(
            deck,
            scan,
            leader_definition=leader_definition,
            ruleset=ruleset,
        )
    )
    return tuple(errors)


def _leader_count_errors(
    deck: DeckDefinition,
    scan: _DeckCardScan,
    *,
    ruleset: DeckRuleset,
) -> tuple[DeckValidationError, ...]:
    if not ruleset.require_single_leader:
        return ()
    leader_count = int(bool(str(deck.leader_id).strip())) + scan.embedded_leader_count
    if leader_count <= 1:
        return ()
    return (
        _error(
            "multiple_leaders",
            f"Deck must include exactly one leader, found {leader_count}.",
        ),
    )


def _composition_errors(
    scan: _DeckCardScan,
    *,
    ruleset: DeckRuleset,
) -> tuple[DeckValidationError, ...]:
    errors: list[DeckValidationError] = []
    if scan.unit_count < ruleset.min_unit_cards:
        message = (
            f"Deck must contain at least {ruleset.min_unit_cards} unit cards, "
            f"found {scan.unit_count}."
        )
        errors.append(
            _error(
                "too_few_unit_cards",
                message,
            )
        )
    if scan.special_count > ruleset.max_special_cards:
        message = (
            f"Deck may contain at most {ruleset.max_special_cards} special cards, "
            f"found {scan.special_count}."
        )
        errors.append(
            _error(
                "too_many_special_cards",
                message,
            )
        )
    return tuple(errors)


def _faction_errors(
    deck: DeckDefinition,
    scan: _DeckCardScan,
    *,
    leader_definition: LeaderDefinition | None,
    ruleset: DeckRuleset,
) -> tuple[DeckValidationError, ...]:
    if not ruleset.enforce_faction or leader_definition is None:
        return ()
    errors: list[DeckValidationError] = []
    if leader_definition.faction != deck.faction:
        message = (
            f"Deck faction {deck.faction.value!r} does not match leader faction "
            f"{leader_definition.faction.value!r}."
        )
        errors.append(
            _error(
                "leader_faction_mismatch",
                message,
            )
        )
    if scan.off_faction_card_ids:
        ids = _joined_ids(scan.off_faction_card_ids)
        errors.append(
            _error(
                "card_faction_mismatch",
                f"Deck contains off-faction non-neutral cards: {ids}.",
            )
        )
    return tuple(errors)


def _error(code: str, message: str) -> DeckValidationError:
    return DeckValidationError(code=code, message=message)


def _joined_ids(definition_ids: tuple[CardDefinitionId, ...]) -> str:
    unique_ids = tuple(dict.fromkeys(str(definition_id) for definition_id in definition_ids))
    return ", ".join(repr(definition_id) for definition_id in unique_ids)


def _validate_copy_limits(
    definition_ids: tuple[CardDefinitionId, ...],
    card_registry: CardRegistry,
) -> tuple[DeckValidationError, ...]:
    counts = Counter(definition_ids)
    errors: list[DeckValidationError] = []
    for definition_id in dict.fromkeys(definition_ids):
        count = counts[definition_id]
        definition = card_registry.get(definition_id)
        limit = definition.effective_max_copies_per_deck()
        if count <= limit:
            continue
        message = (
            f"Card {definition.name!r} ({definition.definition_id!s}) appears {count} times "
            f"but limit is {limit}."
        )
        errors.append(
            _error(
                "too_many_copies",
                message,
            )
        )
    return tuple(errors)
