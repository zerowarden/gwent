"""Bundled engine data: file locations and cached runtime registries."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from gwent_engine.cards import CardRegistry, load_card_definitions
from gwent_engine.decks import DeckDefinition
from gwent_engine.decks import load_sample_decks as load_sample_deck_definitions
from gwent_engine.leaders import LeaderRegistry, load_leader_definitions


def bundled_data_dir() -> Path:
    return Path(str(files("gwent_engine").joinpath("data")))


def bundled_data_path(filename: str) -> Path:
    return bundled_data_dir() / filename


@lru_cache(maxsize=1)
def load_card_registry() -> CardRegistry:
    return CardRegistry.from_definitions(load_card_definitions(bundled_data_path("cards.yaml")))


@lru_cache(maxsize=1)
def load_leader_registry() -> LeaderRegistry:
    return LeaderRegistry.from_definitions(
        load_leader_definitions(bundled_data_path("leaders.yaml"))
    )


@lru_cache(maxsize=1)
def load_sample_decks() -> tuple[DeckDefinition, ...]:
    return load_sample_deck_definitions(
        bundled_data_path("sample_decks.yaml"),
        load_card_registry(),
        load_leader_registry(),
    )


@lru_cache(maxsize=1)
def load_sample_deck_map() -> Mapping[str, DeckDefinition]:
    return MappingProxyType({str(deck.deck_id): deck for deck in load_sample_decks()})
