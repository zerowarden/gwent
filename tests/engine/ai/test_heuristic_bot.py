from __future__ import annotations

from gwent_engine.ai.actions import enumerate_legal_actions, enumerate_mulligan_selections
from gwent_engine.ai.baseline import DEFAULT_BASELINE_CONFIG, HeuristicBot
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.context import classify_context
from gwent_engine.ai.baseline.evaluation import explain_action_score
from gwent_engine.ai.baseline.profile_catalog import get_base_profile_definition
from gwent_engine.ai.baseline.profiles import compose_profile
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import ChoiceSourceKind, GameStatus, Phase, Row
from gwent_engine.core.actions import (
    LeaveAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId, ChoiceId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_REVEAL_HAND_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    build_sample_game_state,
    build_started_game_state,
    choose_bot_response,
    legal_actions_for,
)
from .test_baseline_support import (
    make_clear_weather_leader_state,
    make_final_round_cow_setup_state,
    make_final_round_horned_gap_state,
    make_mardroeme_transform_choice_state,
    make_opponent_passed_guaranteed_win_state,
    make_opponent_passed_spy_draw_catch_up_state,
    make_round_three_visible_win_state,
    make_steel_forged_noop_state,
    make_unsafe_pass_winning_play_state,
)


def test_heuristic_bot_chooses_legal_mulligan_selection() -> None:
    state, _ = build_started_game_state()
    bot = HeuristicBot()
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)

    selected = bot.choose_mulligan(
        observation,
        legal_selections,
        card_registry=CARD_REGISTRY,
    )

    assert selected in legal_selections


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


def test_heuristic_bot_does_not_open_with_dead_villentretenmerth_when_crone_muster_is_live() -> (
    None
):
    state = (
        scenario("heuristic_opening_dead_vill_vs_live_crone")
        .player(
            "p1",
            faction="monsters",
            hand=[
                card("p1_vill", "neutral_villentretenmerth"),
                card("p1_brewess", "monsters_crone_brewess"),
            ],
            deck=[
                card("p1_weavess", "monsters_crone_weavess"),
                card("p1_whispess", "monsters_crone_whispess"),
            ],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_unit", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_brewess"),
        target_row=Row.CLOSE,
    )


def test_heuristic_bot_uses_return_from_discard_leader_over_passing() -> None:
    state = (
        scenario("heuristic_return_leader_over_pass")
        .round(2)
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_bringer_of_death",
            discard=[card("p1_return_catapult", "northern_realms_catapult")],
        )
        .player("p2", leader_used=True, hand=[card("p2_hidden", "scoiatael_dol_blathanna_archer")])
        .build()
    )

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert selected == UseLeaderAbilityAction(player_id=PLAYER_ONE_ID)


def test_heuristic_bot_uses_safe_pass_when_ahead_and_resources_are_preserved() -> None:
    state = (
        scenario("heuristic_safe_pass")
        .player(
            "p1",
            hand=[card("p1_backup_unit", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p1_board_unit", "neutral_geralt")]),
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_board_unit", "scoiatael_vrihedd_brigade_recruit")]),
        )
        .build()
    )
    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PassAction(player_id=PLAYER_ONE_ID)


def test_conservative_bot_does_not_pass_when_one_card_secures_a_safe_lead() -> None:
    state = make_unsafe_pass_winning_play_state()

    selected = choose_bot_response(
        HeuristicBot(
            profile_definition=get_base_profile_definition("conservative"),
        ),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)
    assert selected.card_instance_id == CardInstanceId("p1_yennefer_finisher")


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


def test_heuristic_bot_does_not_choose_noop_steel_forged_leader() -> None:
    state = make_steel_forged_noop_state()

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)
    assert selected.card_instance_id == CardInstanceId("p1_catapult")


def test_conservative_bot_does_not_pass_too_early_in_elimination_round() -> None:
    hidden_cards = [
        card(f"p1_hidden_{index}", "scoiatael_dol_blathanna_archer") for index in range(8)
    ]
    state = (
        scenario("conservative_elimination_round")
        .round(2)
        .current_player("p2")
        .player(
            "p1",
            gems_remaining=1,
            hand=hidden_cards,
            board=rows(
                close=[card("p1_board_geralt", "neutral_geralt")],
                ranged=[card("p1_board_yennefer", "neutral_yennefer")],
                siege=[card("p1_board_archer", "scoiatael_dol_blathanna_archer")],
            ),
        )
        .player(
            "p2",
            gems_remaining=1,
            hand=[
                card("p2_geralt", "neutral_geralt"),
                card("p2_ciri", "neutral_ciri"),
                card("p2_yennefer", "neutral_yennefer"),
                card("p2_scorch", "neutral_scorch"),
            ],
            board=rows(
                close=[card("p2_board_ciri", "neutral_ciri")],
                ranged=[card("p2_board_geralt", "neutral_geralt")],
                siege=[
                    card("p2_board_yennefer", "neutral_yennefer"),
                    card("p2_board_archer", "scoiatael_dol_blathanna_archer"),
                ],
            ),
        )
        .build()
    )
    selected = choose_bot_response(
        HeuristicBot(profile_definition=get_base_profile_definition("conservative")),
        state,
        player_id=PLAYER_TWO_ID,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)


def test_heuristic_bot_contests_final_round_when_effectively_behind_after_pass() -> None:
    state = make_final_round_horned_gap_state()

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_geralt_finisher"),
        target_row=Row.CLOSE,
    )


def test_heuristic_bot_does_not_play_cow_as_dead_final_round_setup() -> None:
    state = make_final_round_cow_setup_state()

    selected = choose_bot_response(
        HeuristicBot(profile_definition=get_base_profile_definition("conservative")),
        state,
        player_id=PLAYER_TWO_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_TWO_ID,
        card_instance_id=CardInstanceId("p2_small_unit"),
        target_row=Row.RANGED,
    )


def test_heuristic_bot_does_not_choose_leave_when_pass_is_available() -> None:
    state = (
        scenario("heuristic_no_leave")
        .round(3)
        .player("p1", gems_remaining=1)
        .player(
            "p2",
            gems_remaining=1,
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_board_unit", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    legal_actions = legal_actions_for(state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY)
    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert LeaveAction(player_id=PLAYER_ONE_ID) in legal_actions
    assert selected == PassAction(player_id=PLAYER_ONE_ID)


def test_heuristic_bot_does_not_waste_scorch_on_empty_opponent_board() -> None:
    state = (
        scenario("heuristic_no_empty_board_scorch")
        .player(
            "p1",
            hand=[
                card("p1_scorch", "neutral_scorch"),
                card("p1_archer", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected != PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_scorch"),
    )


def test_heuristic_bot_does_not_waste_scorch_without_live_targets() -> None:
    state = (
        scenario("heuristic_no_live_target_scorch")
        .player(
            "p1",
            hand=[
                card("p1_scorch", "neutral_scorch"),
                card("p1_archer", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .player(
            "p2",
            board=rows(close=[card("p2_recruit", "scoiatael_vrihedd_brigade_recruit")]),
        )
        .build()
    )
    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected != PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_scorch"),
    )


def test_scorch_score_recognizes_horn_boosted_opponent_target() -> None:
    state = (
        scenario("horn_boosted_opponent_scorch")
        .player(
            "p1",
            hand=[card("p1_scorch", "neutral_scorch")],
        )
        .player(
            "p2",
            leader_horn_row=Row.CLOSE,
            board=rows(close=[card("p2_defender", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = legal_actions_for(state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY)
    action = next(
        action
        for action in legal_actions
        if isinstance(action, PlayCardAction)
        and action.card_instance_id == CardInstanceId("p1_scorch")
    )
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    assert any(term.name == "scorch_policy" for term in breakdown.terms)


def test_scorch_score_penalizes_horn_boosted_self_damage() -> None:
    state = (
        scenario("horn_boosted_self_scorch")
        .player(
            "p1",
            leader_horn_row=Row.CLOSE,
            hand=[card("p1_scorch", "neutral_scorch")],
            board=rows(close=[card("p1_defender", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = legal_actions_for(state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY)
    action = next(
        action
        for action in legal_actions
        if isinstance(action, PlayCardAction)
        and action.card_instance_id == CardInstanceId("p1_scorch")
    )
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    assert ("scorch_live_targets", profile.action_bonus.scorch_self_damage_penalty) in {
        (term.name, term.value) for term in breakdown.terms
    }


def test_decoy_scores_above_leader_in_a_reclaimable_spy_spot() -> None:
    state = (
        scenario("heuristic_decoy_over_leader")
        .round(3)
        .player(
            "p1",
            faction="nilfgaard",
            leader_id=NILFGAARD_REVEAL_HAND_LEADER_ID,
            gems_remaining=1,
            hand=[card("p1_decoy", "neutral_decoy")],
            board=rows(ranged=[card("p1_spy_target", "neutral_mysterious_elf", owner="p2")]),
        )
        .player(
            "p2",
            faction="nilfgaard",
            leader_id=NILFGAARD_REVEAL_HAND_LEADER_ID,
            gems_remaining=1,
            hand=[
                card("p2_hidden_card_1", "scoiatael_dol_blathanna_archer"),
                card("p2_hidden_card_2", "scoiatael_vrihedd_brigade_recruit"),
                card("p2_hidden_card_3", "scoiatael_vrihedd_brigade_recruit"),
                card("p2_hidden_card_4", "scoiatael_dol_blathanna_archer"),
            ],
            board=rows(close=[card("p2_board_hero", "neutral_geralt")]),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    observation = build_player_observation(state, PLAYER_ONE_ID)
    assessment = build_assessment(
        observation,
        CARD_REGISTRY,
        legal_actions=legal_actions,
    )
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    decoy_breakdown = explain_action_score(
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_decoy"),
        ),
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )
    leader_breakdown = explain_action_score(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    assert decoy_breakdown.total > leader_breakdown.total


def test_leader_score_explanation_exposes_named_terms() -> None:
    state = (
        scenario("heuristic_leader_explain")
        .player(
            "p1",
            faction="scoiatael",
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            board=rows(ranged=[card("p1_ranged_unit", "scoiatael_dol_blathanna_archer")]),
        )
        .player(
            "p2",
            faction="scoiatael",
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )
    assessment = build_assessment(
        observation,
        CARD_REGISTRY,
        legal_actions=legal_actions,
    )
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)
    breakdown = explain_action_score(
        UseLeaderAbilityAction(
            player_id=PLAYER_ONE_ID,
            target_row=Row.RANGED,
        ),
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    assert any(
        term.name in {"leader_reserve_cost", "leader_commitment_cost"} for term in breakdown.terms
    )
    assert not any(term.name == "leader_policy" for term in breakdown.terms)


def test_live_clear_weather_leader_scores_above_pass() -> None:
    state = make_clear_weather_leader_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    assessment = build_assessment(
        observation,
        card_registry=CARD_REGISTRY,
        legal_actions=legal_actions,
    )
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    leader_breakdown = explain_action_score(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    pass_breakdown = explain_action_score(
        PassAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert leader_breakdown.total > pass_breakdown.total


def test_heuristic_bot_prefers_minimum_commitment_finish_after_opponent_passes() -> None:
    state = make_opponent_passed_guaranteed_win_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    selected = HeuristicBot().choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_small_finisher"),
        target_row=Row.RANGED,
    )


def test_heuristic_bot_does_not_pass_when_a_spy_line_can_still_draw_into_deck() -> None:
    state = make_opponent_passed_spy_draw_catch_up_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    selected = HeuristicBot(
        profile_definition=get_base_profile_definition("conservative"),
    ).choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)
    assert selected.card_instance_id == CardInstanceId("p1_spy_line")


def test_heuristic_bot_chooses_visible_round_three_winning_line() -> None:
    state = make_round_three_visible_win_state()

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_large_unit"),
        target_row=Row.CLOSE,
    )


def test_heuristic_bot_does_not_horn_a_hero_only_row() -> None:
    state = (
        scenario("heuristic_no_hero_only_horn")
        .round(2)
        .player(
            "p1",
            gems_remaining=1,
            hand=[
                card("p1_horn_special", "neutral_commanders_horn"),
                card("p1_close_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(ranged=[card("p1_yennefer_hero", "neutral_yennefer")]),
        )
        .player(
            "p2",
            gems_remaining=1,
            board=rows(close=[card("p2_close_frontliner", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    selected = HeuristicBot().choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_close_defender"),
        target_row=Row.CLOSE,
    )


def test_heuristic_bot_does_not_horn_an_already_horned_row() -> None:
    state = (
        scenario("heuristic_no_redundant_horn")
        .round(2)
        .player(
            "p1",
            leader_used=True,
            leader_horn_row=Row.CLOSE,
            gems_remaining=1,
            hand=[
                card("p1_horn_special", "neutral_commanders_horn"),
                card("p1_close_defender_b", "scoiatael_mahakaman_defender"),
            ],
            board=rows(close=[card("p1_close_defender_a", "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            gems_remaining=1,
            board=rows(close=[card("p2_close_frontliner", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    selected = HeuristicBot().choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected != PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_horn_special"),
        target_row=Row.CLOSE,
    )


def test_heuristic_bot_completes_seeded_game_legally() -> None:
    rng = SeededRandom(707)
    state = build_sample_game_state()
    bots = {
        PLAYER_ONE_ID: HeuristicBot(bot_id="heuristic_p1"),
        PLAYER_TWO_ID: HeuristicBot(bot_id="heuristic_p2"),
    }
    state, _ = apply_action(
        state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=rng,
        leader_registry=LEADER_REGISTRY,
    )

    for _ in range(256):
        if state.status == GameStatus.MATCH_ENDED:
            break
        if state.phase == Phase.MULLIGAN:
            selections: list[MulliganSelection] = []
            for player_id in (PLAYER_ONE_ID, PLAYER_TWO_ID):
                legal_selections = enumerate_mulligan_selections(state, player_id)
                selection = bots[player_id].choose_mulligan(
                    build_player_observation(state, player_id),
                    legal_selections,
                    card_registry=CARD_REGISTRY,
                    leader_registry=LEADER_REGISTRY,
                )
                assert selection in legal_selections
                selections.append(selection)
            state, _ = apply_action(
                state,
                ResolveMulligansAction(selections=tuple(selections)),
                rng=rng,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )
            continue
        if state.pending_choice is not None:
            acting_player_id = state.pending_choice.player_id
            legal_actions = enumerate_legal_actions(
                state,
                player_id=acting_player_id,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
                rng=rng,
            )
            action = bots[acting_player_id].choose_pending_choice(
                build_player_observation(state, acting_player_id),
                legal_actions,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )
        else:
            acting_player_id = state.current_player
            assert acting_player_id is not None
            legal_actions = enumerate_legal_actions(
                state,
                player_id=acting_player_id,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
                rng=rng,
            )
            action = bots[acting_player_id].choose_action(
                build_player_observation(state, acting_player_id),
                legal_actions,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )
        assert action in legal_actions
        state, _ = apply_action(
            state,
            action,
            rng=rng,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )

    assert state.status == GameStatus.MATCH_ENDED
