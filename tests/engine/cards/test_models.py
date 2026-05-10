from typing import cast

import pytest
from gwent_engine.cards.models import CardDefinition, DeckDefinition
from gwent_engine.core import (
    AbilityKind,
    CardType,
    FactionId,
    GameStatus,
    LeaderAbilityKind,
    LeaderAbilityMode,
    LeaderSelectionMode,
    PassiveKind,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    DeckId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.state import CardInstance, GameState, LeaderState, PlayerState, RowState
from gwent_engine.factions.models import FactionDefinition
from gwent_engine.leaders.models import LeaderDefinition


def _build_card_definition(**overrides: object) -> CardDefinition:
    values: dict[str, object] = {
        "definition_id": CardDefinitionId("northern_realms_test_unit"),
        "name": "Test Unit",
        "faction": FactionId.NORTHERN_REALMS,
        "card_type": CardType.UNIT,
        "base_strength": 4,
        "allowed_rows": (Row.CLOSE,),
        "ability_kinds": (),
        "musters_group": None,
        "muster_group": None,
        "bond_group": None,
        "transforms_into_definition_id": None,
        "avenger_summon_definition_id": None,
        "generated_only": False,
        "max_copies_per_deck": None,
        "is_hero": False,
    }
    values.update(overrides)
    return CardDefinition(
        definition_id=cast(CardDefinitionId, values["definition_id"]),
        name=cast(str, values["name"]),
        faction=cast(FactionId, values["faction"]),
        card_type=cast(CardType, values["card_type"]),
        base_strength=cast(int, values["base_strength"]),
        allowed_rows=cast(tuple[Row, ...], values["allowed_rows"]),
        ability_kinds=cast(tuple[AbilityKind, ...], values["ability_kinds"]),
        musters_group=cast(str | None, values["musters_group"]),
        muster_group=cast(str | None, values["muster_group"]),
        bond_group=cast(str | None, values["bond_group"]),
        transforms_into_definition_id=cast(
            CardDefinitionId | None,
            values["transforms_into_definition_id"],
        ),
        avenger_summon_definition_id=cast(
            CardDefinitionId | None,
            values["avenger_summon_definition_id"],
        ),
        generated_only=cast(bool, values["generated_only"]),
        max_copies_per_deck=cast(int | None, values["max_copies_per_deck"]),
        is_hero=cast(bool, values["is_hero"]),
    )


def _assert_card_definition_rejected(
    *,
    overrides: dict[str, object],
    message: str,
    defaults: dict[str, object] | None = None,
) -> None:
    with pytest.raises(ValueError, match=message):
        _ = _build_card_definition(**{**(defaults or {}), **overrides})


def test_typed_models_construct_cleanly() -> None:
    faction = FactionDefinition(
        faction_id=FactionId.MONSTERS,
        name="Monsters",
        passive_kind=PassiveKind.MONSTERS_KEEP_ONE_UNIT,
        passive_description="One unit remains after cleanup.",
    )

    card_definition = CardDefinition(
        definition_id=CardDefinitionId("scoiatael_bond_vanguard"),
        name="Bond Vanguard",
        faction=FactionId.SCOIATAEL,
        card_type=CardType.UNIT,
        base_strength=4,
        allowed_rows=(Row.CLOSE,),
        ability_kinds=(AbilityKind.TIGHT_BOND,),
        bond_group="vanguard_line",
    )
    deck_definition = DeckDefinition(
        deck_id=DeckId("monsters_sample"),
        faction=FactionId.MONSTERS,
        leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders"),
        card_definition_ids=(CardDefinitionId("monsters_griffin"),),
    )

    player_one = PlayerState(
        player_id=PlayerId("p1"),
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(CardInstanceId("card_1"),),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    player_two = PlayerState(
        player_id=PlayerId("p2"),
        faction=FactionId.NILFGAARD,
        leader=LeaderState(leader_id=LeaderId("nilfgaard_emhyr_his_imperial_majesty")),
        deck=(),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    game_state = GameState(
        game_id=GameId("game_1"),
        players=(player_one, player_two),
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("card_1"),
                definition_id=CardDefinitionId("monsters_griffin"),
                owner=PlayerId("p1"),
                zone=Zone.DECK,
            ),
        ),
        phase=Phase.NOT_STARTED,
        status=GameStatus.NOT_STARTED,
    )

    assert faction.name == "Monsters"
    assert card_definition.allowed_rows == (Row.CLOSE,)
    assert card_definition.bond_group == "vanguard_line"
    assert deck_definition.card_definition_ids == (CardDefinitionId("monsters_griffin"),)
    assert game_state.player(PlayerId("p1")).faction == FactionId.MONSTERS


def test_leader_definition_rejects_specific_weather_mode_without_a_weather_kind() -> None:
    with pytest.raises(ValueError, match="specific mode must declare a weather"):
        _ = LeaderDefinition(
            leader_id=LeaderId("monsters_test_weather_leader"),
            name="Test Weather Leader",
            faction=FactionId.MONSTERS,
            ability_kind=LeaderAbilityKind.PLAY_WEATHER_FROM_DECK,
            ability_mode=LeaderAbilityMode.ACTIVE,
            selection_mode=LeaderSelectionMode.SPECIFIC,
        )


SPECIAL_CARD_METADATA_DEFAULTS: dict[str, object] = {
    "definition_id": CardDefinitionId("neutral_test_special"),
    "name": "Test Special",
    "faction": FactionId.NEUTRAL,
    "card_type": CardType.SPECIAL,
    "base_strength": 0,
    "allowed_rows": (),
    "ability_kinds": (AbilityKind.SCORCH,),
}

LEADER_CARD_METADATA_DEFAULTS: dict[str, object] = {
    "definition_id": CardDefinitionId("monsters_test_leader_card"),
    "name": "Test Leader Card",
    "faction": FactionId.MONSTERS,
    "card_type": CardType.LEADER,
    "base_strength": 0,
    "allowed_rows": (),
    "ability_kinds": (),
}


@pytest.mark.parametrize(
    ("defaults", "overrides", "message"),
    (
        (None, {"name": "   "}, "name cannot be blank"),
        (None, {"musters_group": "   "}, "musters_group cannot be blank"),
        (None, {"muster_group": "   "}, "muster_group cannot be blank"),
        (None, {"bond_group": "   "}, "bond_group cannot be blank"),
        (None, {"base_strength": -1}, "base_strength cannot be negative"),
        (None, {"max_copies_per_deck": 0}, "max_copies_per_deck must be at least 1"),
        (
            None,
            {"allowed_rows": (Row.CLOSE, Row.CLOSE)},
            "allowed_rows cannot contain duplicates",
        ),
        (
            None,
            {"ability_kinds": (AbilityKind.SPY, AbilityKind.SPY)},
            "ability_kinds cannot contain duplicates",
        ),
        (None, {"allowed_rows": ()}, "Unit cards must declare at least one allowed row"),
        (
            None,
            {"ability_kinds": (AbilityKind.MUSTER,)},
            "Muster units must declare a musters_group or muster_group",
        ),
        (
            None,
            {"musters_group": "test_group"},
            "Only Muster units may declare a musters_group",
        ),
        (
            None,
            {"ability_kinds": (AbilityKind.TIGHT_BOND,)},
            "Tight Bond units must declare a bond_group",
        ),
        (
            None,
            {"bond_group": "bond_line"},
            "Only Tight Bond units may declare a bond_group",
        ),
        (
            None,
            {"ability_kinds": (AbilityKind.BERSERKER,)},
            "Berserker units must declare transforms_into_definition_id",
        ),
        (
            None,
            {"transforms_into_definition_id": CardDefinitionId("skellige_transformed_vildkaarl")},
            "Only Berserker units may declare transforms_into_definition_id",
        ),
        (
            None,
            {"ability_kinds": (AbilityKind.AVENGER,)},
            "Avenger units must declare avenger_summon_definition_id",
        ),
        (
            None,
            {"avenger_summon_definition_id": CardDefinitionId("neutral_bovine_defense_force")},
            "Only Avenger units may declare avenger_summon_definition_id",
        ),
        (
            SPECIAL_CARD_METADATA_DEFAULTS,
            {
                "card_type": CardType.SPECIAL,
                "base_strength": 1,
                "ability_kinds": (AbilityKind.SCORCH,),
            },
            "Special cards must not carry base strength",
        ),
        (
            SPECIAL_CARD_METADATA_DEFAULTS,
            {
                "card_type": CardType.SPECIAL,
                "is_hero": True,
                "ability_kinds": (AbilityKind.SCORCH,),
            },
            "Only unit cards may be marked as heroes",
        ),
        (
            SPECIAL_CARD_METADATA_DEFAULTS,
            {
                "card_type": CardType.SPECIAL,
                "ability_kinds": (AbilityKind.SCORCH,),
                "muster_group": "test_group",
            },
            "Special cards cannot declare unit metadata",
        ),
        (
            SPECIAL_CARD_METADATA_DEFAULTS,
            {"card_type": CardType.SPECIAL, "ability_kinds": ()},
            "Special cards must declare exactly one ability_kind",
        ),
        (
            SPECIAL_CARD_METADATA_DEFAULTS,
            {
                "card_type": CardType.SPECIAL,
                "ability_kinds": (AbilityKind.SCORCH,),
                "allowed_rows": (Row.CLOSE,),
            },
            "Only row-targeted special cards may declare allowed_rows",
        ),
        (
            SPECIAL_CARD_METADATA_DEFAULTS,
            {
                "card_type": CardType.SPECIAL,
                "ability_kinds": (AbilityKind.COMMANDERS_HORN,),
                "allowed_rows": (),
            },
            "Row-targeted special cards must declare at least one allowed row",
        ),
        (
            LEADER_CARD_METADATA_DEFAULTS,
            {"card_type": CardType.LEADER, "base_strength": 1},
            "Only unit cards may carry base strength",
        ),
        (
            LEADER_CARD_METADATA_DEFAULTS,
            {"card_type": CardType.LEADER, "is_hero": True},
            "Only unit cards may be marked as heroes",
        ),
        (
            LEADER_CARD_METADATA_DEFAULTS,
            {"card_type": CardType.LEADER, "allowed_rows": (Row.CLOSE,)},
            "Only unit or horn cards may declare allowed_rows",
        ),
        (
            LEADER_CARD_METADATA_DEFAULTS,
            {"card_type": CardType.LEADER, "muster_group": "test_group"},
            "Only unit cards may declare unit metadata",
        ),
    ),
)
def test_card_definition_rejects_invalid_metadata(
    defaults: dict[str, object] | None,
    overrides: dict[str, object],
    message: str,
) -> None:
    _assert_card_definition_rejected(
        defaults=defaults,
        overrides=overrides,
        message=message,
    )


def test_card_definition_accepts_valid_special_row_card() -> None:
    card_definition = _build_card_definition(
        definition_id=CardDefinitionId("neutral_test_horn"),
        name="Test Horn",
        faction=FactionId.NEUTRAL,
        card_type=CardType.SPECIAL,
        base_strength=0,
        allowed_rows=(Row.CLOSE,),
        ability_kinds=(AbilityKind.COMMANDERS_HORN,),
    )

    assert card_definition.ability_kinds == (AbilityKind.COMMANDERS_HORN,)
    assert card_definition.allowed_rows == (Row.CLOSE,)


def test_card_definition_accepts_valid_ability_bound_unit_metadata() -> None:
    card_definition = _build_card_definition(
        definition_id=CardDefinitionId("skellige_test_berserker_avenger"),
        name="Test Berserker Avenger",
        faction=FactionId.SKELLIGE,
        ability_kinds=(AbilityKind.BERSERKER, AbilityKind.AVENGER),
        transforms_into_definition_id=CardDefinitionId("skellige_transformed_vildkaarl"),
        avenger_summon_definition_id=CardDefinitionId("neutral_bovine_defense_force"),
    )

    assert card_definition.transforms_into_definition_id == CardDefinitionId(
        "skellige_transformed_vildkaarl"
    )
    assert card_definition.avenger_summon_definition_id == CardDefinitionId(
        "neutral_bovine_defense_force"
    )


def test_card_definition_allows_one_way_muster_membership_without_trigger() -> None:
    card_definition = _build_card_definition(
        definition_id=CardDefinitionId("skellige_clan_drummond_shield_maiden"),
        name="Clan Drummond Shield Maiden",
        faction=FactionId.SKELLIGE,
        ability_kinds=(AbilityKind.TIGHT_BOND,),
        muster_group="drummond_shieldmaiden",
        bond_group="clan_drummond_shield_maiden",
    )

    assert card_definition.muster_group == "drummond_shieldmaiden"
    assert card_definition.resolved_musters_group is None


def test_card_definition_resolves_backward_compatible_muster_trigger_group() -> None:
    card_definition = _build_card_definition(
        definition_id=CardDefinitionId("monsters_arachas"),
        name="Arachas",
        faction=FactionId.MONSTERS,
        ability_kinds=(AbilityKind.MUSTER,),
        muster_group="arachas",
    )

    assert card_definition.resolved_musters_group == "arachas"


def test_card_definition_uses_singleton_default_copy_limit_when_undeclared() -> None:
    card_definition = _build_card_definition()

    assert card_definition.effective_max_copies_per_deck() == 1


def test_card_definition_uses_declared_copy_limit_when_present() -> None:
    card_definition = _build_card_definition(max_copies_per_deck=3)

    assert card_definition.effective_max_copies_per_deck() == 3


def test_deck_definition_rejects_empty_card_list() -> None:
    with pytest.raises(ValueError, match="must contain at least one card definition id"):
        _ = DeckDefinition(
            deck_id=DeckId("empty_test_deck"),
            faction=FactionId.MONSTERS,
            leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders"),
            card_definition_ids=(),
        )
