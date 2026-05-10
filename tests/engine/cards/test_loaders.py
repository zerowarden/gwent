from collections.abc import Callable
from pathlib import Path

import pytest
from gwent_engine.cards.loaders import load_card_definitions
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import FactionId, LeaderAbilityKind, LeaderSelectionMode, PassiveKind
from gwent_engine.core.errors import (
    DefinitionLoadError,
    UnknownAbilityKindError,
    UnknownLeaderAbilityKindError,
    UnknownPassiveKindError,
)
from gwent_engine.core.ids import CardDefinitionId, LeaderId
from gwent_engine.decks import load_sample_decks
from gwent_engine.factions.loaders import load_faction_definitions
from gwent_engine.leaders.loaders import load_leader_definitions
from gwent_engine.leaders.registry import LeaderRegistry

from tests.support import write_yaml_fixture

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"


def _assert_loader_rejects(
    tmp_path: Path,
    *,
    filename: str,
    content: str,
    loader: Callable[[Path], object],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _ = loader(write_yaml_fixture(tmp_path, filename, content))


def test_sample_yaml_loads_successfully() -> None:
    faction_definitions = load_faction_definitions(DATA_DIR / "factions.yaml")
    card_definitions = load_card_definitions(DATA_DIR / "cards.yaml")
    card_registry = CardRegistry.from_definitions(card_definitions)
    leader_definitions = load_leader_definitions(DATA_DIR / "leaders.yaml")
    leader_registry = LeaderRegistry.from_definitions(leader_definitions)
    deck_definitions = load_sample_decks(
        DATA_DIR / "sample_decks.yaml",
        card_registry,
        leader_registry,
    )

    assert len(faction_definitions) == 5
    assert len(card_definitions) == 158
    assert len(leader_definitions) == 22
    assert len(deck_definitions) == 16
    assert faction_definitions[0].passive_kind == PassiveKind.MONSTERS_KEEP_ONE_UNIT
    assert faction_definitions[-1].passive_kind == (
        PassiveKind.SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE
    )
    assert deck_definitions[0].faction == FactionId.MONSTERS
    assert len(deck_definitions[0].card_definition_ids) == 25
    assert (
        card_registry.get(CardDefinitionId("neutral_bovine_defense_force")).generated_only is True
    )
    assert leader_registry.get(LeaderId("monsters_eredin_king_of_the_wild_hunt")).ability_kind == (
        LeaderAbilityKind.PLAY_WEATHER_FROM_DECK
    )
    assert (
        leader_registry.get(LeaderId("monsters_eredin_king_of_the_wild_hunt")).selection_mode
        == LeaderSelectionMode.CHOOSE
    )
    assert leader_registry.get(LeaderId("skellige_king_bran")).faction == FactionId.SKELLIGE


@pytest.mark.parametrize(
    ("filename", "content", "loader", "error_type", "message"),
    (
        (
            "factions.yaml",
            """
factions:
  - faction_id: monsters
    name: Monsters
    passive_kind: not_a_real_passive
    passive_description: Broken
""",
            load_faction_definitions,
            UnknownPassiveKindError,
            "Unknown passive_kind",
        ),
        (
            "factions.yaml",
            """
factions:
  - faction_id: not_a_real_faction
    name: Broken Faction
    passive_kind: monsters_keep_one_unit
    passive_description: Broken
""",
            load_faction_definitions,
            DefinitionLoadError,
            "Unknown faction id",
        ),
        (
            "cards.yaml",
            """
cards:
  - definition_id: monsters_griffin
    name: Griffin
    faction: monsters
    card_type: unit
    base_strength: 5
    allowed_rows: [close]
    ability_kinds: [not_a_real_ability]
""",
            load_card_definitions,
            UnknownAbilityKindError,
            "Unknown ability_kind",
        ),
    ),
)
def test_loader_rejects_unknown_yaml_symbols(
    tmp_path: Path,
    filename: str,
    content: str,
    loader: Callable[[Path], object],
    error_type: type[Exception],
    message: str,
) -> None:
    _assert_loader_rejects(
        tmp_path,
        filename=filename,
        content=content,
        loader=loader,
        error_type=error_type,
        message=message,
    )


def test_muster_cards_require_a_trigger_group(tmp_path: Path) -> None:
    _assert_loader_rejects(
        tmp_path,
        filename="cards.yaml",
        content="""
cards:
  - definition_id: scoiatael_muster_warband
    name: Warband Fighter
    faction: scoiatael
    card_type: unit
    base_strength: 2
    allowed_rows: [close]
    ability_kinds: [muster]
""",
        loader=load_card_definitions,
        error_type=ValueError,
        message="musters_group or muster_group",
    )


def test_loader_accepts_explicit_one_way_muster_schema(tmp_path: Path) -> None:
    file_path = write_yaml_fixture(
        tmp_path,
        "cards.yaml",
        """
cards:
  - definition_id: skellige_cerys
    name: Cerys
    faction: skellige
    card_type: unit
    base_strength: 10
    allowed_rows: [close]
    ability_kinds: [muster]
    musters_group: drummond_shieldmaiden
  - definition_id: skellige_clan_drummond_shield_maiden
    name: Clan Drummond Shield Maiden
    faction: skellige
    card_type: unit
    base_strength: 4
    allowed_rows: [close]
    ability_kinds: [tight_bond]
    muster_group: drummond_shieldmaiden
    bond_group: clan_drummond_shield_maiden
""",
    )

    card_definitions = load_card_definitions(file_path)
    cerys, shield_maiden = card_definitions

    assert cerys.resolved_musters_group == "drummond_shieldmaiden"
    assert shield_maiden.muster_group == "drummond_shieldmaiden"


@pytest.mark.parametrize(
    ("filename", "content", "loader", "error_type", "message"),
    (
        (
            "cards.yaml",
            """
cards:
  - definition_id: scoiatael_bond_vanguard
    name: Bond Vanguard
    faction: scoiatael
    card_type: unit
    base_strength: 4
    allowed_rows: [close]
    ability_kinds: [tight_bond]
""",
            load_card_definitions,
            ValueError,
            "bond_group",
        ),
        (
            "cards.yaml",
            """
cards:
  - definition_id: northern_realms_test_ballista
    name: Test Ballista
    faction: northern_realms
    card_type: unit
    base_strength: 6
    allowed_rows: [siege]
    ability_kinds: []
    max_copies_per_deck: 0
""",
            load_card_definitions,
            ValueError,
            "max_copies_per_deck must be at least 1",
        ),
        (
            "leaders.yaml",
            """
leaders:
  - leader_id: scoiatael_broken_leader
    name: Broken Leader
    faction: scoiatael
    ability_kind: not_a_real_leader_ability
    ability_mode: active
""",
            load_leader_definitions,
            UnknownLeaderAbilityKindError,
            "Unknown leader_ability_kind",
        ),
    ),
)
def test_loader_rejects_invalid_card_and_leader_metadata(
    tmp_path: Path,
    filename: str,
    content: str,
    loader: Callable[[Path], object],
    error_type: type[Exception],
    message: str,
) -> None:
    _assert_loader_rejects(
        tmp_path,
        filename=filename,
        content=content,
        loader=loader,
        error_type=error_type,
        message=message,
    )


def test_generated_only_cards_are_rejected_from_decks(tmp_path: Path) -> None:
    cards_path = tmp_path / "cards.yaml"
    _ = cards_path.write_text(
        """
cards:
  - definition_id: neutral_bovine_defense_force
    name: Bovine Defense Force
    faction: neutral
    card_type: unit
    base_strength: 8
    allowed_rows: [close]
    ability_kinds: []
    generated_only: true
""".strip(),
        encoding="utf-8",
    )
    decks_path = tmp_path / "sample_decks.yaml"
    _ = decks_path.write_text(
        """
decks:
  - deck_id: monsters_invalid_generated_deck
    faction: monsters
    leader_id: monsters_eredin_commander_of_the_red_riders
    cards:
      - neutral_bovine_defense_force
""".strip(),
        encoding="utf-8",
    )

    card_registry = CardRegistry.from_definitions(load_card_definitions(cards_path))
    leader_registry = LeaderRegistry.from_definitions(
        load_leader_definitions(DATA_DIR / "leaders.yaml")
    )

    with pytest.raises(DefinitionLoadError, match="generated-only"):
        _ = load_sample_decks(decks_path, card_registry, leader_registry)
