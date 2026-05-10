from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.pending_choice import choose_pending_choice_action
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import ChoiceKind, ChoiceSourceKind, Row
from gwent_engine.core.actions import ResolveChoiceAction
from gwent_engine.core.ids import CardInstanceId, ChoiceId

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_choose_pending_choice_action_prefers_close_for_row_selection() -> None:
    state = (
        scenario("row_choice_state")
        .player("p1", hand=[card("p1_decoy_source", "neutral_decoy")])
        .pending_choice(
            choice_id="row_choice",
            player_id="p1",
            kind=ChoiceKind.SELECT_CARD_INSTANCE,
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=(),
            legal_rows=(Row.CLOSE, Row.RANGED, Row.SIEGE),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert action == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("row_choice"),
        selected_rows=(Row.CLOSE,),
    )


def test_choose_pending_choice_action_prefers_spy_target_for_decoy() -> None:
    state = (
        scenario("decoy_choice_state")
        .player(
            "p1",
            hand=[card("p1_decoy_source", "neutral_decoy")],
            board=rows(
                close=[
                    card("p1_spy_target", "nilfgaard_vattier_de_rideaux"),
                    card("p1_plain_target", "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .card_choice(
            choice_id="decoy_choice",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=("p1_spy_target", "p1_plain_target"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert action.selected_card_instance_ids == (CardInstanceId("p1_spy_target"),)


def test_choose_pending_choice_action_prefers_stronger_medic_target() -> None:
    state = (
        scenario("medic_choice_state")
        .player(
            "p1",
            discard=[
                card("p1_discard_small", "scoiatael_dol_blathanna_archer"),
                card("p1_discard_large", "nilfgaard_black_infantry_archer"),
            ],
            board=rows(ranged=[card("p1_medic_source", "nilfgaard_etolian_auxilary_archer")]),
        )
        .card_choice(
            choice_id="medic_choice",
            player_id="p1",
            source_kind=ChoiceSourceKind.MEDIC,
            source_card_instance_id="p1_medic_source",
            legal_target_card_instance_ids=("p1_discard_small", "p1_discard_large"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert action.selected_card_instance_ids == (CardInstanceId("p1_discard_large"),)


def test_choose_pending_choice_action_avoids_spy_medic_target_when_deck_is_empty() -> None:
    state = (
        scenario("medic_pending_choice_empty_deck_state")
        .player(
            "p1",
            discard=[
                card("p1_discard_spy", "nilfgaard_shilard_fitz_oesterlen"),
                card("p1_discard_catapult", "northern_realms_catapult"),
            ],
            board=rows(ranged=[card("p1_medic_source", "nilfgaard_etolian_auxilary_archer")]),
        )
        .card_choice(
            choice_id="medic_pending_choice_empty_deck",
            player_id="p1",
            source_kind=ChoiceSourceKind.MEDIC,
            source_card_instance_id="p1_medic_source",
            legal_target_card_instance_ids=("p1_discard_spy", "p1_discard_catapult"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert action.selected_card_instance_ids == (CardInstanceId("p1_discard_catapult"),)


def test_leader_discard_and_choose_prefers_weak_discards_and_best_pick() -> None:
    state = (
        scenario("leader_discard_and_choose_pending_choice")
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_destroyer_of_worlds",
            hand=[
                card("p1_discard_recruit", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_discard_archer", "scoiatael_dol_blathanna_archer"),
            ],
            deck=[
                card("p1_pick_geralt", "neutral_geralt"),
                card("p1_skip_trebuchet", "northern_realms_trebuchet"),
            ],
        )
        .leader_choice(
            choice_id="leader_discard_and_choose_choice",
            player_id="p1",
            source_leader_id="monsters_eredin_destroyer_of_worlds",
            legal_target_card_instance_ids=(
                "p1_discard_recruit",
                "p1_discard_archer",
                "p1_pick_geralt",
                "p1_skip_trebuchet",
            ),
            min_selections=3,
            max_selections=3,
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY),
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert set(action.selected_card_instance_ids) == {
        CardInstanceId("p1_discard_recruit"),
        CardInstanceId("p1_discard_archer"),
        CardInstanceId("p1_pick_geralt"),
    }


def test_choose_pending_choice_action_return_leader_prefers_best_own_discard() -> None:
    state = (
        scenario("leader_return_own_discard_pending_choice")
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_bringer_of_death",
            discard=[
                card("p1_return_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_return_catapult", "northern_realms_catapult"),
            ],
        )
        .leader_choice(
            choice_id="leader_return_choice",
            player_id="p1",
            source_leader_id="monsters_eredin_bringer_of_death",
            legal_target_card_instance_ids=("p1_return_archer", "p1_return_catapult"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY),
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert action.selected_card_instance_ids == (CardInstanceId("p1_return_catapult"),)


def test_choose_pending_choice_action_steal_leader_prefers_best_opponent_discard() -> None:
    state = (
        scenario("leader_steal_opponent_discard_pending_choice")
        .player(
            "p1",
            faction="nilfgaard",
            leader_id="nilfgaard_emhyr_the_relentless",
        )
        .player(
            "p2",
            discard=[
                card("p2_steal_hero", "neutral_geralt"),
                card("p2_steal_catapult", "northern_realms_catapult"),
            ],
        )
        .leader_choice(
            choice_id="leader_steal_choice",
            player_id="p1",
            source_leader_id="nilfgaard_emhyr_the_relentless",
            legal_target_card_instance_ids=("p2_steal_hero", "p2_steal_catapult"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY),
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert action.selected_card_instance_ids == (CardInstanceId("p2_steal_catapult"),)


def test_choose_pending_choice_action_leader_uses_opponent_discard_from_viewer_perspective() -> (
    None
):
    state = (
        scenario("leader_steal_opponent_discard_pending_choice_p2")
        .player(
            "p1",
            discard=[
                card("a_target_vill", "neutral_villentretenmerth"),
                card("z_target_crone", "monsters_crone_weavess"),
            ],
        )
        .player(
            "p2",
            faction="nilfgaard",
            leader_id="nilfgaard_emhyr_the_relentless",
        )
        .leader_choice(
            choice_id="leader_steal_choice_p2",
            player_id="p2",
            source_leader_id="nilfgaard_emhyr_the_relentless",
            legal_target_card_instance_ids=("a_target_vill", "z_target_crone"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_TWO_ID)

    action = choose_pending_choice_action(
        build_player_observation(state, PLAYER_TWO_ID, LEADER_REGISTRY),
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert action.selected_card_instance_ids == (CardInstanceId("a_target_vill"),)
