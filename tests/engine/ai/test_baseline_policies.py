from gwent_engine.ai.baseline import (
    DEFAULT_BASELINE_CONFIG,
    OPPORTUNISTIC_SCORCH_POLICY,
    RESERVE_SCORCH_POLICY,
    compose_profile,
    get_base_profile_definition,
)
from gwent_engine.ai.baseline.assessment import RowSummary
from gwent_engine.ai.baseline.context import classify_context
from gwent_engine.ai.baseline.policies.leader import leader_policy_components
from gwent_engine.ai.baseline.projection import ScorchImpact
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.ids import CardInstanceId, PlayerId

from .test_baseline_support import make_assessment, make_player_assessment


def test_compose_profile_uses_base_profile_policy_defaults() -> None:
    assessment = make_assessment(card_advantage=1)
    context = classify_context(assessment)

    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    assert profile.scorch_policy.name == "opportunistic_scorch"
    assert profile.leader_policy.name == "aggressive"


def test_compose_profile_uses_selected_profile_policy_defaults() -> None:
    assessment = make_assessment(
        score_gap=-2,
        viewer_board_strength=4,
        opponent_board_strength=6,
        is_elimination_round=True,
    )
    context = classify_context(assessment)

    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=get_base_profile_definition("conservative"),
    )

    assert profile.scorch_policy.name == "reserve_scorch"
    assert profile.leader_policy.name == "conservative"


def test_reserve_scorch_policy_scores_lower_than_opportunistic_scorch_policy() -> None:
    preserve_assessment = make_assessment(
        viewer=make_player_assessment(
            player_id="p1",
            close=RowSummary(
                row=Row.CLOSE,
                unit_count=1,
                non_hero_unit_count=1,
                non_hero_unit_base_strength=2,
                base_strength=2,
            ),
        ),
        opponent=make_player_assessment(
            player_id="p2",
            close=RowSummary(
                row=Row.CLOSE,
                unit_count=1,
                non_hero_unit_count=1,
                non_hero_unit_base_strength=8,
                base_strength=8,
            ),
        ),
        card_advantage=1,
    )
    preserve_context = classify_context(preserve_assessment)
    preserve_profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        preserve_assessment,
        preserve_context,
    )
    tempo_assessment = make_assessment(
        score_gap=-1,
        viewer=make_player_assessment(
            player_id="p1",
            close=RowSummary(
                row=Row.CLOSE,
                unit_count=1,
                non_hero_unit_count=1,
                non_hero_unit_base_strength=3,
                base_strength=3,
            ),
        ),
        opponent=make_player_assessment(
            player_id="p2",
            close=RowSummary(
                row=Row.CLOSE,
                unit_count=1,
                non_hero_unit_count=1,
                non_hero_unit_base_strength=10,
                base_strength=10,
            ),
        ),
        is_elimination_round=True,
    )
    tempo_context = classify_context(tempo_assessment)
    tempo_profile = compose_profile(DEFAULT_BASELINE_CONFIG, tempo_assessment, tempo_context)
    action = PlayCardAction(
        player_id=PlayerId("p1"),
        card_instance_id=CardInstanceId("scorch_card"),
    )

    reserve_score = RESERVE_SCORCH_POLICY.evaluate(
        action=action,
        assessment=preserve_assessment,
        context=preserve_context,
        scorch_impact=ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=10),
        profile=preserve_profile,
    )
    opportunistic_score = OPPORTUNISTIC_SCORCH_POLICY.evaluate(
        action=action,
        assessment=tempo_assessment,
        context=tempo_context,
        scorch_impact=ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=10),
        profile=tempo_profile,
    )

    assert opportunistic_score > reserve_score


def test_reserve_scorch_policy_penalizes_dead_scorch() -> None:
    assessment = make_assessment(
        viewer_board_strength=6,
        opponent_board_strength=0,
    )
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)
    action = PlayCardAction(
        player_id=PlayerId("p1"),
        card_instance_id=CardInstanceId("scorch_card"),
    )

    score = RESERVE_SCORCH_POLICY.evaluate(
        action=action,
        assessment=assessment,
        context=context,
        scorch_impact=ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=0),
        profile=profile,
    )

    assert score == profile.action_bonus.invalid_target_penalty


def test_reserve_scorch_policy_penalizes_self_damaging_scorch() -> None:
    assessment = make_assessment(
        viewer_board_strength=10,
        opponent_board_strength=10,
    )
    context = classify_context(assessment)
    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)
    action = PlayCardAction(
        player_id=PlayerId("p1"),
        card_instance_id=CardInstanceId("scorch_card"),
    )

    score = RESERVE_SCORCH_POLICY.evaluate(
        action=action,
        assessment=assessment,
        context=context,
        scorch_impact=ScorchImpact(viewer_strength_lost=10, opponent_strength_lost=10),
        profile=profile,
    )

    assert score == profile.action_bonus.invalid_target_penalty


def test_conservative_leader_policy_discourages_spending_leader_without_pressure() -> None:
    assessment = make_assessment(card_advantage=1)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=get_base_profile_definition("conservative"),
    )

    components = leader_policy_components(
        policy_name=profile.leader_policy.name,
        assessment=assessment,
        context=context,
        profile=profile,
    )

    assert components == (
        (
            "leader_reserve_cost",
            -(profile.weights.leader_value * 6.0 * max(profile.preserve_resources_bias, 1.0)),
        ),
    )


def test_aggressive_leader_policy_scores_higher_under_elimination_pressure() -> None:
    preserve_assessment = make_assessment(card_advantage=1)
    preserve_context = classify_context(preserve_assessment)
    preserve_profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        preserve_assessment,
        preserve_context,
        base_profile=get_base_profile_definition("conservative"),
    )
    tempo_assessment = make_assessment(
        score_gap=-4,
        viewer_board_strength=4,
        opponent_board_strength=8,
        is_elimination_round=True,
    )
    tempo_context = classify_context(tempo_assessment)
    tempo_profile = compose_profile(DEFAULT_BASELINE_CONFIG, tempo_assessment, tempo_context)

    preserve_score = sum(
        value
        for _, value in leader_policy_components(
            policy_name=preserve_profile.leader_policy.name,
            assessment=preserve_assessment,
            context=preserve_context,
            profile=preserve_profile,
        )
    )
    tempo_score = sum(
        value
        for _, value in leader_policy_components(
            policy_name=tempo_profile.leader_policy.name,
            assessment=tempo_assessment,
            context=tempo_context,
            profile=tempo_profile,
        )
    )

    assert tempo_score > preserve_score
