from pathlib import Path
from typing import cast

import pytest
from gwent_engine.cards.loaders import load_card_definitions
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import FactionId
from gwent_engine.core.errors import UnknownCardDefinitionError, UnknownFactionError
from gwent_engine.core.ids import CardDefinitionId
from gwent_engine.factions.loaders import load_faction_definitions
from gwent_engine.factions.registry import FactionRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"


def test_card_registry_lookup_succeeds_for_known_ids() -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))

    card = registry.get(CardDefinitionId("monsters_griffin"))

    assert card.name == "Griffin"


def test_card_registry_lookup_fails_for_unknown_ids() -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))

    with pytest.raises(UnknownCardDefinitionError, match="Unknown card definition id"):
        registry.get(CardDefinitionId("missing_card"))


def test_faction_registry_lookup_succeeds_for_known_ids() -> None:
    registry = FactionRegistry.from_definitions(
        load_faction_definitions(DATA_DIR / "factions.yaml")
    )

    faction = registry.get(FactionId.SCOIATAEL)

    assert faction.name == "Scoia'tael"


def test_faction_registry_lookup_fails_for_unknown_ids() -> None:
    registry = FactionRegistry.from_definitions(
        load_faction_definitions(DATA_DIR / "factions.yaml")
    )

    with pytest.raises(UnknownFactionError, match="Unknown faction id"):
        registry.get(cast(FactionId, cast(object, "not_a_faction")))
