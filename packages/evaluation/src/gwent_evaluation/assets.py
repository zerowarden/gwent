from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.cards import CardDefinition, CardRegistry, DeckDefinition
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.runtime_assets import (
    load_card_registry,
    load_leader_registry,
    load_sample_deck_map,
)
from gwent_shared.error_translation import translate_mapping_key

from gwent_evaluation.provenance import canonical_digest


@dataclass(frozen=True, slots=True)
class ResolvedAssets:
    """Runtime assets resolved once and addressed by their stable identifiers."""

    decks: Mapping[str, DeckDefinition]
    card_registry: CardRegistry
    leader_registry: LeaderRegistry

    def deck(self, deck_id: str) -> DeckDefinition:
        return translate_mapping_key(
            self.decks,
            deck_id,
            lambda _deck_id: ValueError(f"Unknown sample deck id: {deck_id!r}"),
        )

    def deck_digest(self, deck_id: str) -> str:
        return canonical_digest(self.deck(deck_id))

    def card_data_digest(self) -> str:
        return canonical_digest(card_catalog(self.card_registry))

    def leader_data_digest(self) -> str:
        return canonical_digest(leader_catalog(self.leader_registry))


def resolve_assets() -> ResolvedAssets:
    return ResolvedAssets(
        decks=load_sample_deck_map(),
        card_registry=load_card_registry(),
        leader_registry=load_leader_registry(),
    )


def card_catalog(card_registry: CardRegistry) -> tuple[CardDefinition, ...]:
    return tuple(sorted(card_registry, key=lambda definition: str(definition.definition_id)))


def leader_catalog(leader_registry: LeaderRegistry) -> tuple[LeaderDefinition, ...]:
    return tuple(sorted(leader_registry, key=lambda definition: str(definition.leader_id)))
