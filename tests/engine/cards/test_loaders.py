from collections.abc import Callable
from pathlib import Path

import pytest
from gwent_engine.assets import bundled_data_dir
from gwent_engine.cards.loaders import load_card_definitions
from gwent_engine.cards.models import CardRegistry
from gwent_engine.core import (
    AbilityKind,
    FactionId,
    LeaderAbilityKind,
    LeaderSelectionMode,
    Row,
)
from gwent_engine.core.errors import (
    DefinitionLoadError,
    UnknownAbilityKindError,
    UnknownLeaderAbilityKindError,
)
from gwent_engine.core.ids import CardDefinitionId, LeaderId
from gwent_engine.decks import load_sample_decks
from gwent_engine.leaders.loaders import load_leader_definitions
from gwent_engine.leaders.models import LeaderRegistry

from tests.support import write_yaml_fixture

DATA_DIR = bundled_data_dir()


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
    card_definitions = load_card_definitions(DATA_DIR / "cards.yaml")
    card_registry = CardRegistry.from_definitions(card_definitions)
    leader_definitions = load_leader_definitions(DATA_DIR / "leaders.yaml")
    leader_registry = LeaderRegistry.from_definitions(leader_definitions)
    deck_definitions = load_sample_decks(
        DATA_DIR / "sample_decks.yaml",
        card_registry,
        leader_registry,
    )

    assert len(card_definitions) == 165
    assert len(leader_definitions) == 22
    assert len(deck_definitions) == 16
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
    ("definition_id", "name", "faction", "strength", "rows", "is_hero"),
    (
        ("monsters_frightener", "Frightener", FactionId.MONSTERS, 5, (Row.CLOSE,), False),
        ("monsters_ice_giant", "Ice Giant", FactionId.MONSTERS, 5, (Row.SIEGE,), False),
        ("nilfgaard_cynthia", "Cynthia", FactionId.NILFGAARD, 4, (Row.RANGED,), False),
        ("scoiatael_iorveth", "Iorveth", FactionId.SCOIATAEL, 10, (Row.RANGED,), True),
        ("monsters_grave_hag", "Grave Hag", FactionId.MONSTERS, 5, (Row.RANGED,), False),
        ("monsters_wyvern", "Wyvern", FactionId.MONSTERS, 2, (Row.RANGED,), False),
    ),
)
def test_reconciled_catalog_cards(
    definition_id: str,
    name: str,
    faction: FactionId,
    strength: int,
    rows: tuple[Row, ...],
    is_hero: bool,
) -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))
    definition = registry.get(CardDefinitionId(definition_id))

    assert (definition.name, definition.faction, definition.base_strength) == (
        name,
        faction,
        strength,
    )
    assert definition.allowed_rows == rows
    assert definition.is_hero is is_hero
    assert definition.ability_kinds == ()


@pytest.mark.parametrize("hero_id", ("neutral_geralt", "neutral_ciri"))
def test_roach_reward_is_an_optional_hero_variant(hero_id: str) -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))
    ordinary = registry.get(CardDefinitionId(hero_id))
    rewarded = registry.get(CardDefinitionId(f"{hero_id}_with_roach"))
    roach = registry.get(CardDefinitionId("neutral_roach"))

    assert ordinary.ability_kinds == ()
    assert rewarded.name == ordinary.name
    assert rewarded.is_hero
    assert rewarded.ability_kinds == (AbilityKind.MUSTER,)
    assert rewarded.resolved_musters_group == roach.muster_group == "roach"
    assert rewarded.muster_from_deck_only
    assert (roach.faction, roach.base_strength, roach.allowed_rows, roach.is_hero) == (
        FactionId.NEUTRAL,
        3,
        (Row.CLOSE,),
        False,
    )


@pytest.mark.parametrize(
    ("definition_id", "name"),
    (
        ("monsters_nekkar", "Nekker"),
        ("northern_realms_crinfrid_reaver", "Crinfrid Reavers Dragon Hunter"),
        ("nilfgaard_cahir", "Cahir Mawr Dyffryn aep Ceallach"),
        ("nilfgaard_etolian_auxilary_archer", "Etolian Auxiliary Archers"),
        ("nilfgaard_morvan_voorhis", "Morvran Voorhis"),
        ("scoiatael_dennis_cranmer", "Dennis Cranmer"),
        ("skellige_clan_an_craie_warrior", "Clan an Craite Warrior"),
    ),
)
def test_reconciled_catalog_names(definition_id: str, name: str) -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))

    assert registry.get(CardDefinitionId(definition_id)).name == name


@pytest.mark.parametrize(
    ("definition_id", "copies"),
    (
        ("monsters_nekkar", 3),
        ("nilfgaard_black_infantry_archer", 2),
        ("nilfgaard_etolian_auxilary_archer", 2),
        ("nilfgaard_nausicaa_cavalry_rider", 3),
        ("nilfgaard_young_emissary", 2),
        ("northern_realms_catapult", 2),
        ("scoiatael_dwarven_skirmisher", 3),
        ("scoiatael_elven_skirmisher", 3),
        ("scoiatael_havekar_healer", 3),
        ("scoiatael_mahakaman_defender", 5),
        ("scoiatael_vrihedd_brigade_veteran", 2),
        ("skellige_clan_an_craie_warrior", 3),
        ("skellige_clan_brokvar_archer", 3),
        ("skellige_light_longship", 3),
        ("skellige_mardroeme", 3),
    ),
)
def test_collectible_copy_limits(definition_id: str, copies: int) -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))

    assert registry.get(CardDefinitionId(definition_id)).effective_max_copies_per_deck() == copies


@pytest.mark.parametrize("definition_id", ("monsters_draug", "skellige_hjalmar"))
def test_reconciled_hero_flags(definition_id: str) -> None:
    registry = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))

    assert registry.get(CardDefinitionId(definition_id)).is_hero


@pytest.mark.parametrize(
    ("filename", "content", "loader", "error_type", "message"),
    (
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
