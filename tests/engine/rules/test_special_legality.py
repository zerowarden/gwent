import pytest
from gwent_engine.cards.models import CardDefinition
from gwent_engine.core import AbilityKind, CardType, FactionId, Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardDefinitionId

from tests.engine.rules.support import (
    assert_play_rejected,
    build_registry_with_extra,
    play_action,
    validate_play,
)
from tests.engine.scenario_builder import ScenarioRows, card, rows, scenario


@pytest.mark.parametrize(
    (
        "scenario_name",
        "hand_card_instance_id",
        "hand_card_definition_id",
        "action",
        "message",
        "board",
    ),
    [
        (
            "legality_reject_invalid_horn_states",
            "p1_horn_special_in_hand",
            "neutral_commanders_horn",
            play_action(
                "p1_horn_special_in_hand",
                target_row=Row.CLOSE,
                target_card_instance_id="p1_archer_target",
            ),
            "Commander's Horn does not target a battlefield card.",
            rows(),
        ),
        (
            "legality_reject_invalid_horn_states",
            "p1_horn_special_in_hand",
            "neutral_commanders_horn",
            play_action("p1_horn_special_in_hand"),
            "Commander's Horn must target a combat row.",
            rows(),
        ),
        (
            "legality_reject_invalid_horn_states",
            "p1_horn_special_in_hand",
            "neutral_commanders_horn",
            play_action("p1_horn_special_in_hand", target_row=Row.CLOSE),
            "more than one Commander's Horn",
            rows(close=[card("p1_existing_horn_on_close_row", "neutral_commanders_horn")]),
        ),
        (
            "legality_reject_invalid_horn_states",
            "p1_horn_special_in_hand",
            "neutral_commanders_horn",
            play_action("p1_horn_special_in_hand", target_row=Row.CLOSE),
            "Special Mardroeme and special Horn cannot share a row.",
            rows(close=[card("p1_existing_mardroeme_on_close_row", "skellige_mardroeme")]),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            play_action(
                "p1_mardroeme_special_in_hand",
                target_row=Row.CLOSE,
                target_card_instance_id="p1_archer_target",
            ),
            "Mardroeme does not target a battlefield card.",
            rows(),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            play_action("p1_mardroeme_special_in_hand"),
            "Mardroeme must target a combat row.",
            rows(),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            play_action("p1_mardroeme_special_in_hand", target_row=Row.CLOSE),
            "Special Mardroeme and special Horn cannot share a row.",
            rows(close=[card("p1_existing_horn_on_close_row", "neutral_commanders_horn")]),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            play_action("p1_mardroeme_special_in_hand", target_row=Row.CLOSE),
            "more than one special Mardroeme",
            rows(close=[card("p1_existing_mardroeme_on_close_row", "skellige_mardroeme")]),
        ),
        (
            "legality_reject_invalid_decoy_states",
            "p1_decoy_special_in_hand",
            "neutral_decoy",
            play_action("p1_decoy_special_in_hand", target_row=Row.CLOSE),
            "Decoy targets a battlefield card, not a combat row.",
            rows(),
        ),
        (
            "legality_reject_invalid_decoy_states",
            "p1_decoy_special_in_hand",
            "neutral_decoy",
            play_action(
                "p1_decoy_special_in_hand",
                target_card_instance_id="p1_vanguard_frontliner",
            ),
            "Decoy battlefield targets are resolved through pending choice.",
            rows(close=[card("p1_vanguard_frontliner", "scoiatael_mahakaman_defender")]),
        ),
        (
            "legality_reject_invalid_decoy_states",
            "p1_decoy_special_in_hand",
            "neutral_decoy",
            play_action("p1_decoy_special_in_hand"),
            "valid non-hero unit card on your battlefield",
            rows(close=[card("p1_geralt_hero_frontliner", "neutral_geralt")]),
        ),
    ],
)
def test_targeted_special_legality_rejects_invalid_states(
    scenario_name: str,
    hand_card_instance_id: str,
    hand_card_definition_id: str,
    action: PlayCardAction,
    message: str,
    board: ScenarioRows,
) -> None:
    assert_play_rejected(
        scenario_name=scenario_name,
        hand_card_instance_id=hand_card_instance_id,
        hand_card_definition_id=hand_card_definition_id,
        action=action,
        message=message,
        board=board,
    )


def test_commanders_horn_legality_rejects_invalid_row() -> None:
    horn_only_ranged_definition = CardDefinition(
        definition_id=CardDefinitionId("synthetic_ranged_horn_special"),
        name="Synthetic Ranged Horn",
        faction=FactionId.NEUTRAL,
        card_type=CardType.SPECIAL,
        base_strength=0,
        allowed_rows=(Row.RANGED,),
        ability_kinds=(AbilityKind.COMMANDERS_HORN,),
    )
    state = (
        scenario("legality_reject_invalid_horn_row")
        .player(
            "p1",
            hand=[card("p1_ranged_horn_special_in_hand", "synthetic_ranged_horn_special")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="cannot be played to row"):
        validate_play(
            state,
            play_action("p1_ranged_horn_special_in_hand", target_row=Row.CLOSE),
            card_registry=build_registry_with_extra(horn_only_ranged_definition),
        )


def test_commanders_horn_legality_accepts_open_row() -> None:
    state = (
        scenario("legality_accept_open_horn_row")
        .player("p1", hand=[card("p1_horn_special_in_hand", "neutral_commanders_horn")])
        .build()
    )

    validate_play(
        state,
        play_action("p1_horn_special_in_hand", target_row=Row.CLOSE),
    )


def test_special_mardroeme_legality_rejects_invalid_row() -> None:
    mardroeme_only_siege_definition = CardDefinition(
        definition_id=CardDefinitionId("synthetic_siege_mardroeme_special"),
        name="Synthetic Siege Mardroeme",
        faction=FactionId.NEUTRAL,
        card_type=CardType.SPECIAL,
        base_strength=0,
        allowed_rows=(Row.SIEGE,),
        ability_kinds=(AbilityKind.MARDROEME,),
    )
    state = (
        scenario("legality_reject_invalid_mardroeme_row")
        .player(
            "p1",
            hand=[card("p1_siege_mardroeme_special_in_hand", "synthetic_siege_mardroeme_special")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="cannot be played to row"):
        validate_play(
            state,
            play_action("p1_siege_mardroeme_special_in_hand", target_row=Row.CLOSE),
            card_registry=build_registry_with_extra(mardroeme_only_siege_definition),
        )


def test_special_mardroeme_legality_accepts_open_row() -> None:
    state = (
        scenario("legality_accept_open_mardroeme_row")
        .player("p1", hand=[card("p1_mardroeme_special_in_hand", "skellige_mardroeme")])
        .build()
    )

    validate_play(
        state,
        play_action("p1_mardroeme_special_in_hand", target_row=Row.CLOSE),
    )


@pytest.mark.parametrize(
    ("definition_id", "action", "message"),
    [
        (
            "neutral_biting_frost",
            play_action("p1_weather_special_in_hand", target_row=Row.CLOSE),
            "does not target a combat row",
        ),
        (
            "neutral_clear_weather",
            play_action(
                "p1_weather_special_in_hand",
                target_card_instance_id="p1_archer_target",
            ),
            "does not target a battlefield card",
        ),
    ],
)
def test_global_special_legality_rejects_row_and_battlefield_targets(
    definition_id: str,
    action: PlayCardAction,
    message: str,
) -> None:
    state = (
        scenario("legality_reject_global_special_targets")
        .player("p1", hand=[card("p1_weather_special_in_hand", definition_id)])
        .build()
    )

    with pytest.raises(IllegalActionError, match=message):
        validate_play(state, action)


@pytest.mark.parametrize(
    "definition_id",
    ["neutral_biting_frost", "neutral_clear_weather", "neutral_scorch"],
)
def test_global_special_legality_accepts_no_targets(definition_id: str) -> None:
    state = (
        scenario("legality_accept_global_special_without_targets")
        .player("p1", hand=[card("p1_global_special_in_hand", definition_id)])
        .build()
    )

    validate_play(state, play_action("p1_global_special_in_hand"))


def test_decoy_legality_accepts_valid_battlefield_unit() -> None:
    state = (
        scenario("legality_accept_valid_decoy_target")
        .player(
            "p1",
            hand=[card("p1_decoy_special_in_hand", "neutral_decoy")],
            board=rows(close=[card("p1_vanguard_frontliner", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    validate_play(state, play_action("p1_decoy_special_in_hand"))


def test_special_legality_rejects_unsupported_special_ability_kinds() -> None:
    unsupported_special_definition = CardDefinition(
        definition_id=CardDefinitionId("synthetic_agile_special"),
        name="Synthetic Agile Special",
        faction=FactionId.NEUTRAL,
        card_type=CardType.SPECIAL,
        base_strength=0,
        allowed_rows=(),
        ability_kinds=(AbilityKind.AGILE,),
    )
    state = (
        scenario("legality_reject_unsupported_special_kind")
        .player("p1", hand=[card("p1_unsupported_special_in_hand", "synthetic_agile_special")])
        .build()
    )

    with pytest.raises(IllegalActionError, match="Unsupported special ability kind"):
        validate_play(
            state,
            play_action("p1_unsupported_special_in_hand"),
            card_registry=build_registry_with_extra(unsupported_special_definition),
        )
