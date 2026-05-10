from pathlib import Path

from gwent_shared.error_translation import translate_exception

from gwent_engine.cards import CardDefinition, CardRegistry, DeckDefinition
from gwent_engine.core import FactionId
from gwent_engine.core.errors import (
    DefinitionLoadError,
    UnknownCardDefinitionError,
    UnknownLeaderDefinitionError,
)
from gwent_engine.core.ids import CardDefinitionId, DeckId, LeaderId
from gwent_engine.core.yaml_parsing import (
    expect_mapping,
    expect_sequence,
    load_yaml_document,
    parse_faction_id,
    require_str,
)
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry


def load_sample_decks(
    path: Path,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> tuple[DeckDefinition, ...]:
    document = expect_mapping(load_yaml_document(path), context=f"{path} root")
    raw_decks = expect_sequence(document.get("decks"), context=f"{path} decks")
    return tuple(
        _build_deck_definition(
            raw_deck,
            path=path,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        for raw_deck in raw_decks
    )


def _build_deck_definition(
    raw_deck: object,
    *,
    path: Path,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> DeckDefinition:
    entry = expect_mapping(raw_deck, context=f"{path} deck entry")
    context = f"{path} deck {entry.get('deck_id', '<missing>')!r}"
    faction = parse_faction_id(require_str(entry, "faction", context=context))
    leader_id = LeaderId(require_str(entry, "leader_id", context=context))
    raw_cards = expect_sequence(entry.get("cards"), context=f"{context} cards")

    leader_definition = _get_deck_leader_definition(
        leader_registry,
        leader_id,
        context=context,
    )
    if leader_definition.faction != faction:
        raise DefinitionLoadError(
            f"{context} references leader {leader_id!r} from faction "
            + f"{leader_definition.faction!r}, expected {faction!r}."
        )

    card_definition_ids: list[CardDefinitionId] = []
    for raw_card_id in raw_cards:
        if not isinstance(raw_card_id, str) or not raw_card_id.strip():
            raise DefinitionLoadError(f"{context} cards entries must be non-blank strings.")
        definition_id = CardDefinitionId(raw_card_id.strip())
        definition = _get_deck_card_definition(
            card_registry,
            definition_id,
            context=context,
        )
        if definition.generated_only:
            raise DefinitionLoadError(
                f"{context} cannot include generated-only card definition id {definition_id!r}."
            )
        if definition.faction not in (faction, FactionId.NEUTRAL):
            raise DefinitionLoadError(
                f"{context} contains {definition_id!r} from faction {definition.faction!r}, "
                + f"expected {faction!r} or {FactionId.NEUTRAL!r}."
            )
        card_definition_ids.append(definition_id)

    _validate_deck_copy_limits(
        context,
        card_definition_ids,
        card_registry=card_registry,
    )

    return DeckDefinition(
        deck_id=DeckId(require_str(entry, "deck_id", context=context)),
        faction=faction,
        leader_id=leader_id,
        card_definition_ids=tuple(card_definition_ids),
    )


def _get_deck_leader_definition(
    leader_registry: LeaderRegistry,
    leader_id: LeaderId,
    *,
    context: str,
) -> LeaderDefinition:
    return translate_exception(
        lambda: leader_registry.get(leader_id),
        UnknownLeaderDefinitionError,
        lambda _exc: DefinitionLoadError(f"{context} references unknown leader id {leader_id!r}."),
    )


def _get_deck_card_definition(
    card_registry: CardRegistry,
    definition_id: CardDefinitionId,
    *,
    context: str,
) -> CardDefinition:
    return translate_exception(
        lambda: card_registry.get(definition_id),
        UnknownCardDefinitionError,
        lambda _exc: DefinitionLoadError(
            f"{context} references unknown card definition id {definition_id!r}."
        ),
    )


def _validate_deck_copy_limits(
    context: str,
    card_definition_ids: list[CardDefinitionId],
    *,
    card_registry: CardRegistry,
) -> None:
    counts: dict[CardDefinitionId, int] = {}
    for definition_id in card_definition_ids:
        counts[definition_id] = counts.get(definition_id, 0) + 1
    for definition_id, count in counts.items():
        definition = card_registry.get(definition_id)
        if definition.max_copies_per_deck is not None and count > definition.max_copies_per_deck:
            raise DefinitionLoadError(
                f"{context} contains {count} copies of {definition_id!r}, "
                + f"exceeding the limit of {definition.max_copies_per_deck}."
            )


__all__ = ["load_sample_decks"]
