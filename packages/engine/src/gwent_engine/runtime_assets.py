from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from gwent_engine.cards import (
    CardRegistry,
    DeckDefinition,
    load_card_definitions,
)
from gwent_engine.decks import load_sample_decks as load_sample_deck_definitions
from gwent_engine.leaders import LeaderRegistry, load_leader_definitions

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = WORKSPACE_ROOT / "data"


@lru_cache(maxsize=1)
def load_card_registry() -> CardRegistry:
    return CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))


@lru_cache(maxsize=1)
def load_leader_registry() -> LeaderRegistry:
    return LeaderRegistry.from_definitions(load_leader_definitions(DATA_DIR / "leaders.yaml"))


@lru_cache(maxsize=1)
def load_sample_decks() -> tuple[DeckDefinition, ...]:
    return load_sample_deck_definitions(
        DATA_DIR / "sample_decks.yaml",
        load_card_registry(),
        load_leader_registry(),
    )


@lru_cache(maxsize=1)
def load_sample_deck_map() -> Mapping[str, DeckDefinition]:
    return MappingProxyType({str(deck.deck_id): deck for deck in load_sample_decks()})
