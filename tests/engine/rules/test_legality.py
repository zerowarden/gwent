import pytest
from gwent_engine.cards.models import CardDefinition
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import AbilityKind, CardType, FactionId, Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState
from gwent_engine.leaders.registry import LeaderRegistry
from gwent_engine.rules.legality import (
    validate_in_round_player_can_act,
    validate_play_card_legality,
)

from tests.engine.scenario_builder import ScenarioRows, card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    IdentityShuffle,
    build_custom_in_round_state,
    make_card_instance,
)


def _play_action(
    card_instance_id: str,
    *,
    target_row: Row | None = None,
    target_card_instance_id: str | None = None,
    secondary_target_card_instance_id: str | None = None,
) -> PlayCardAction:
    return PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId(card_instance_id),
        target_row=target_row,
        target_card_instance_id=(
            CardInstanceId(target_card_instance_id) if target_card_instance_id is not None else None
        ),
        secondary_target_card_instance_id=(
            CardInstanceId(secondary_target_card_instance_id)
            if secondary_target_card_instance_id is not None
            else None
        ),
    )


def _build_registry_with_extra(extra_definition: CardDefinition) -> CardRegistry:
    return CardRegistry.from_definitions((*tuple(CARD_REGISTRY), extra_definition))


def _validate_play(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry = CARD_REGISTRY,
    leader_registry: LeaderRegistry = LEADER_REGISTRY,
    rng: SupportsRandom | None = None,
) -> None:
    validate_play_card_legality(
        state,
        state.player(action.player_id),
        action,
        card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def _assert_play_rejected(
    *,
    scenario_name: str,
    hand_card_instance_id: str,
    hand_card_definition_id: str,
    action: PlayCardAction,
    message: str,
    board: ScenarioRows | None = None,
    faction: str | FactionId | None = None,
    leader_id: str | None = None,
    discard_card_instance_id: str | None = None,
    discard_card_definition_id: str | None = None,
    rng: SupportsRandom | None = None,
) -> None:
    discard_cards = (
        []
        if discard_card_instance_id is None or discard_card_definition_id is None
        else [card(discard_card_instance_id, discard_card_definition_id)]
    )
    state = (
        scenario(scenario_name)
        .player(
            "p1",
            faction=faction,
            leader_id=leader_id,
            hand=[card(hand_card_instance_id, hand_card_definition_id)],
            discard=discard_cards,
            board=board or rows(),
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match=message):
        _validate_play(state, action, rng=rng)


def test_validate_in_round_player_can_act_rejects_passed_player() -> None:
    state = (
        scenario("legality_reject_passed_player")
        .player(
            "p1",
            passed=True,
            hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="Passed players cannot act again"):
        validate_in_round_player_can_act(state, state.player(PLAYER_ONE_ID))


def test_validate_in_round_player_can_act_rejects_non_current_player() -> None:
    state = (
        scenario("legality_reject_non_current_player")
        .current_player("p2")
        .player("p1", hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")])
        .build()
    )

    with pytest.raises(IllegalActionError, match="Only the current player may act"):
        validate_in_round_player_can_act(state, state.player(PLAYER_ONE_ID))


def test_validate_in_round_player_can_act_accepts_current_unpassed_player() -> None:
    state = (
        scenario("legality_accept_current_unpassed_player")
        .player("p1", hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")])
        .build()
    )

    validate_in_round_player_can_act(state, state.player(PLAYER_ONE_ID))


def test_validate_play_card_legality_rejects_card_not_in_hand() -> None:
    state = build_custom_in_round_state(card_instances=())

    with pytest.raises(IllegalActionError, match="is not in player"):
        _validate_play(
            state,
            _play_action("missing_vanguard_in_hand", target_row=Row.CLOSE),
        )


def test_validate_play_card_legality_rejects_wrong_owner() -> None:
    borrowed_card_id = CardInstanceId("p2_vanguard_borrowed_in_hand")
    state = build_custom_in_round_state(
        card_instances=(
            make_card_instance(
                instance_id="p2_vanguard_borrowed_in_hand",
                definition_id="scoiatael_mahakaman_defender",
                owner=PLAYER_TWO_ID,
                zone=Zone.HAND,
            ),
        ),
        player_one_hand=(borrowed_card_id,),
    )

    with pytest.raises(IllegalActionError, match="does not belong to player"):
        _validate_play(
            state,
            _play_action("p2_vanguard_borrowed_in_hand", target_row=Row.CLOSE),
        )


def test_validate_play_card_legality_rejects_card_not_in_hand_zone() -> None:
    misplaced_card_id = CardInstanceId("p1_vanguard_marked_as_deck")
    state = build_custom_in_round_state(
        card_instances=(
            make_card_instance(
                instance_id="p1_vanguard_marked_as_deck",
                definition_id="scoiatael_mahakaman_defender",
                owner=PLAYER_ONE_ID,
                zone=Zone.DECK,
            ),
        ),
        player_one_hand=(misplaced_card_id,),
    )

    with pytest.raises(IllegalActionError, match="must be in hand to be played"):
        _validate_play(
            state,
            _play_action("p1_vanguard_marked_as_deck", target_row=Row.CLOSE),
        )


def test_validate_play_card_legality_rejects_non_unit_non_special_cards() -> None:
    leader_card_definition = CardDefinition(
        definition_id=CardDefinitionId("synthetic_leader_card"),
        name="Synthetic Leader Card",
        faction=FactionId.NEUTRAL,
        card_type=CardType.LEADER,
        base_strength=0,
        allowed_rows=(),
    )
    state = (
        scenario("legality_reject_synthetic_leader_card")
        .player("p1", hand=[card("p1_synthetic_leader_in_hand", "synthetic_leader_card")])
        .build()
    )

    with pytest.raises(IllegalActionError, match="Only unit cards and supported special cards"):
        _validate_play(
            state,
            _play_action("p1_synthetic_leader_in_hand"),
            card_registry=_build_registry_with_extra(leader_card_definition),
        )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (_play_action("p1_vanguard_in_hand"), "Unit cards must target a combat row."),
        (
            _play_action("p1_vanguard_in_hand", target_row=Row.SIEGE),
            "cannot be played to row",
        ),
        (
            _play_action(
                "p1_vanguard_in_hand",
                target_row=Row.CLOSE,
                target_card_instance_id="discard_target_archer",
            ),
            "Only Medic unit cards may target another card",
        ),
        (
            _play_action(
                "p1_vanguard_in_hand",
                target_row=Row.CLOSE,
                secondary_target_card_instance_id="discard_target_archer",
            ),
            "Only Medic unit cards may declare a secondary target",
        ),
    ],
)
def test_non_medic_unit_legality_rejects_invalid_targets(
    action: PlayCardAction,
    message: str,
) -> None:
    _assert_play_rejected(
        scenario_name="legality_reject_non_medic_invalid_targets",
        hand_card_instance_id="p1_vanguard_in_hand",
        hand_card_definition_id="scoiatael_mahakaman_defender",
        action=action,
        message=message,
    )


def test_medic_legality_requires_rng_for_randomized_restore_leader() -> None:
    state = (
        scenario("legality_randomized_medic_requires_rng")
        .player(
            "p1",
            faction="nilfgaard",
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[card("p1_archer_in_discard", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="requires an injected RNG"):
        _validate_play(
            state,
            _play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
            rng=None,
        )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (
            _play_action(
                "p1_field_surgeon_in_hand",
                target_row=Row.RANGED,
                target_card_instance_id="p1_archer_in_discard",
            ),
            "do not allow explicit Medic targets",
        ),
        (
            _play_action(
                "p1_field_surgeon_in_hand",
                target_row=Row.RANGED,
                secondary_target_card_instance_id="p1_archer_in_discard",
            ),
            "do not allow Medic secondary targets",
        ),
    ],
)
def test_randomized_medic_legality_rejects_explicit_targets(
    action: PlayCardAction,
    message: str,
) -> None:
    _assert_play_rejected(
        scenario_name="legality_randomized_medic_reject_explicit_targets",
        faction="nilfgaard",
        leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
        hand_card_instance_id="p1_field_surgeon_in_hand",
        hand_card_definition_id="scoiatael_havekar_healer",
        discard_card_instance_id="p1_archer_in_discard",
        discard_card_definition_id="scoiatael_dol_blathanna_archer",
        action=action,
        message=message,
        rng=IdentityShuffle(),
    )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (
            _play_action(
                "p1_field_surgeon_in_hand",
                target_row=Row.RANGED,
                target_card_instance_id="p1_archer_in_discard",
            ),
            "Medic discard targets are resolved through pending choice.",
        ),
        (
            _play_action(
                "p1_field_surgeon_in_hand",
                target_row=Row.RANGED,
                secondary_target_card_instance_id="p1_archer_in_discard",
            ),
            "Medic discard targets are resolved through pending choice.",
        ),
    ],
)
def test_pending_choice_medic_legality_rejects_explicit_targets(
    action: PlayCardAction,
    message: str,
) -> None:
    _assert_play_rejected(
        scenario_name="legality_pending_choice_medic_reject_explicit_targets",
        hand_card_instance_id="p1_field_surgeon_in_hand",
        hand_card_definition_id="scoiatael_havekar_healer",
        discard_card_instance_id="p1_archer_in_discard",
        discard_card_definition_id="scoiatael_dol_blathanna_archer",
        action=action,
        message=message,
    )


def test_medic_legality_requires_valid_non_hero_unit_in_discard() -> None:
    state = (
        scenario("legality_medic_requires_non_hero_unit")
        .player(
            "p1",
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[
                card("p1_iorveth_hero_in_discard", "neutral_geralt"),
                card("p1_decoy_special_in_discard", "neutral_decoy"),
            ],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="valid non-hero unit card in your discard pile"):
        _validate_play(
            state,
            _play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
        )


def test_medic_legality_accepts_pending_choice_with_valid_discard_target() -> None:
    state = (
        scenario("legality_medic_accepts_valid_discard_target")
        .player(
            "p1",
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[card("p1_archer_in_discard", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    _validate_play(
        state,
        _play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
    )


def test_randomized_medic_legality_accepts_rng_driven_restore() -> None:
    state = (
        scenario("legality_randomized_medic_accepts_rng_restore")
        .player(
            "p1",
            faction="nilfgaard",
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[card("p1_archer_in_discard", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    _validate_play(
        state,
        _play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
        rng=IdentityShuffle(),
    )


def test_non_medic_unit_legality_accepts_clean_row_play() -> None:
    state = (
        scenario("legality_accept_non_medic_clean_row_play")
        .player("p1", hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")])
        .build()
    )

    _validate_play(
        state,
        _play_action("p1_vanguard_in_hand", target_row=Row.CLOSE),
    )


def test_special_legality_rejects_secondary_targets() -> None:
    state = (
        scenario("legality_reject_special_secondary_targets")
        .player("p1", hand=[card("p1_horn_special_in_hand", "neutral_commanders_horn")])
        .build()
    )

    with pytest.raises(IllegalActionError, match="Special cards do not declare a secondary target"):
        _validate_play(
            state,
            _play_action(
                "p1_horn_special_in_hand",
                target_row=Row.CLOSE,
                secondary_target_card_instance_id="p1_archer_target",
            ),
        )


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
            _play_action(
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
            _play_action("p1_horn_special_in_hand"),
            "Commander's Horn must target a combat row.",
            rows(),
        ),
        (
            "legality_reject_invalid_horn_states",
            "p1_horn_special_in_hand",
            "neutral_commanders_horn",
            _play_action("p1_horn_special_in_hand", target_row=Row.CLOSE),
            "more than one Commander's Horn",
            rows(close=[card("p1_existing_horn_on_close_row", "neutral_commanders_horn")]),
        ),
        (
            "legality_reject_invalid_horn_states",
            "p1_horn_special_in_hand",
            "neutral_commanders_horn",
            _play_action("p1_horn_special_in_hand", target_row=Row.CLOSE),
            "Special Mardroeme and special Horn cannot share a row.",
            rows(close=[card("p1_existing_mardroeme_on_close_row", "skellige_mardroeme")]),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            _play_action(
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
            _play_action("p1_mardroeme_special_in_hand"),
            "Mardroeme must target a combat row.",
            rows(),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            _play_action("p1_mardroeme_special_in_hand", target_row=Row.CLOSE),
            "Special Mardroeme and special Horn cannot share a row.",
            rows(close=[card("p1_existing_horn_on_close_row", "neutral_commanders_horn")]),
        ),
        (
            "legality_reject_invalid_mardroeme_states",
            "p1_mardroeme_special_in_hand",
            "skellige_mardroeme",
            _play_action("p1_mardroeme_special_in_hand", target_row=Row.CLOSE),
            "more than one special Mardroeme",
            rows(close=[card("p1_existing_mardroeme_on_close_row", "skellige_mardroeme")]),
        ),
        (
            "legality_reject_invalid_decoy_states",
            "p1_decoy_special_in_hand",
            "neutral_decoy",
            _play_action("p1_decoy_special_in_hand", target_row=Row.CLOSE),
            "Decoy targets a battlefield card, not a combat row.",
            rows(),
        ),
        (
            "legality_reject_invalid_decoy_states",
            "p1_decoy_special_in_hand",
            "neutral_decoy",
            _play_action(
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
            _play_action("p1_decoy_special_in_hand"),
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
    _assert_play_rejected(
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
        _validate_play(
            state,
            _play_action("p1_ranged_horn_special_in_hand", target_row=Row.CLOSE),
            card_registry=_build_registry_with_extra(horn_only_ranged_definition),
        )


def test_commanders_horn_legality_accepts_open_row() -> None:
    state = (
        scenario("legality_accept_open_horn_row")
        .player("p1", hand=[card("p1_horn_special_in_hand", "neutral_commanders_horn")])
        .build()
    )

    _validate_play(
        state,
        _play_action("p1_horn_special_in_hand", target_row=Row.CLOSE),
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
        _validate_play(
            state,
            _play_action("p1_siege_mardroeme_special_in_hand", target_row=Row.CLOSE),
            card_registry=_build_registry_with_extra(mardroeme_only_siege_definition),
        )


def test_special_mardroeme_legality_accepts_open_row() -> None:
    state = (
        scenario("legality_accept_open_mardroeme_row")
        .player("p1", hand=[card("p1_mardroeme_special_in_hand", "skellige_mardroeme")])
        .build()
    )

    _validate_play(
        state,
        _play_action("p1_mardroeme_special_in_hand", target_row=Row.CLOSE),
    )


@pytest.mark.parametrize(
    ("definition_id", "action", "message"),
    [
        (
            "neutral_biting_frost",
            _play_action("p1_weather_special_in_hand", target_row=Row.CLOSE),
            "does not target a combat row",
        ),
        (
            "neutral_clear_weather",
            _play_action(
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
        _validate_play(state, action)


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

    _validate_play(state, _play_action("p1_global_special_in_hand"))


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

    _validate_play(state, _play_action("p1_decoy_special_in_hand"))


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
        _validate_play(
            state,
            _play_action("p1_unsupported_special_in_hand"),
            card_registry=_build_registry_with_extra(unsupported_special_definition),
        )
