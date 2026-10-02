from __future__ import annotations

from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.core import ChoiceSourceKind
from gwent_engine.core.actions import (
    PlayCardAction,
    ResolveChoiceAction,
)
from gwent_engine.core.ids import CardInstanceId, ChoiceId

from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    choose_bot_response,
    legal_actions_for,
)
from ..support import (
    make_mardroeme_transform_choice_state,
)


def test_heuristic_bot_chooses_legal_pending_choice_action() -> None:
    state = (
        scenario("heuristic_pending_choice")
        .player(
            "p1",
            hand=[card("p1_source_decoy", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("p1_spy_target", "neutral_mysterious_elf", owner="p2"),
                    card("p1_archer_target", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .card_choice(
            choice_id="pending_choice_1",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_source_decoy",
            legal_target_card_instance_ids=("p1_spy_target", "p1_archer_target"),
        )
        .build()
    )
    legal_actions = legal_actions_for(state, player_id=PLAYER_ONE_ID)

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        pending_choice=True,
    )

    assert selected in legal_actions
    assert isinstance(selected, ResolveChoiceAction)
    assert selected.selected_card_instance_ids == (CardInstanceId("p1_spy_target"),)


def test_heuristic_bot_prefers_stronger_medic_pending_choice_target() -> None:
    state = (
        scenario("medic_pending_choice_state")
        .player(
            "p1",
            discard=[
                card("p1_discard_small", "scoiatael_dol_blathanna_archer"),
                card("p1_discard_large", "nilfgaard_black_infantry_archer"),
            ],
            board=rows(ranged=[card("p1_medic_source", "nilfgaard_etolian_auxilary_archer")]),
        )
        .card_choice(
            choice_id="medic_pending_choice",
            player_id="p1",
            source_kind=ChoiceSourceKind.MEDIC,
            source_card_instance_id="p1_medic_source",
            legal_target_card_instance_ids=("p1_discard_small", "p1_discard_large"),
        )
        .build()
    )

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        pending_choice=True,
    )

    assert selected == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("medic_pending_choice"),
        selected_card_instance_ids=(CardInstanceId("p1_discard_large"),),
    )


def test_heuristic_bot_avoids_spy_medic_target_when_deck_is_empty() -> None:
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

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        pending_choice=True,
    )

    assert selected == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("medic_pending_choice_empty_deck"),
        selected_card_instance_ids=(CardInstanceId("p1_discard_catapult"),),
    )


def test_heuristic_bot_prefers_best_leader_return_pending_choice_target() -> None:
    state = (
        scenario("heuristic_leader_return_pending_choice")
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

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        pending_choice=True,
    )

    assert selected == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("leader_return_choice"),
        selected_card_instance_ids=(CardInstanceId("p1_return_catapult"),),
    )


def test_heuristic_bot_prefers_villentretenmerth_when_stealing_from_opponent_discard() -> None:
    state = (
        scenario("heuristic_leader_steal_pending_choice_p2")
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

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_TWO_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        pending_choice=True,
    )

    assert selected == ResolveChoiceAction(
        player_id=PLAYER_TWO_ID,
        choice_id=ChoiceId("leader_steal_choice_p2"),
        selected_card_instance_ids=(CardInstanceId("a_target_vill"),),
    )


def test_heuristic_bot_prefers_mardroeme_transform_line() -> None:
    state = make_mardroeme_transform_choice_state()

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)
    assert selected.card_instance_id == CardInstanceId("p1_mardroeme")
