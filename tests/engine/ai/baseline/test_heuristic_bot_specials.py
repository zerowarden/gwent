from __future__ import annotations

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline import DEFAULT_BASELINE_CONFIG, HeuristicBot
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.context import classify_context
from gwent_engine.ai.baseline.evaluation import explain_action_score
from gwent_engine.ai.baseline.profiles import compose_profile
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import Row
from gwent_engine.core.actions import (
    PlayCardAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId

from tests.support import PLAYER_ONE_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    NILFGAARD_REVEAL_HAND_LEADER_ID,
    choose_bot_response,
    legal_actions_for,
)


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
