"""Strategy diagnostics: score-path witnesses, not claims of an optimal move."""

from dataclasses import replace

import pytest
from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.decision_plan import build_decision_plan
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG

from tests.engine.ai.support import make_clear_weather_leader_state
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY, LEADER_REGISTRY, PLAYER_ONE_ID


@pytest.mark.parametrize(
    "weight,special,endpoint",
    [
        ("horn_potential", "neutral_commanders_horn", 2.4),
        ("dead_card_penalty", "neutral_biting_frost", -4.0),
        ("leader_value", "neutral_clear_weather", 16.0),
    ],
)
def test_special_card_paths_have_relative_score_effects(
    weight: str, special: str, endpoint: float
) -> None:
    state = (
        scenario("special_card_sensitivity")
        .player(
            "p1",
            leader_used=True,
            hand=[
                card("special", special),
                card("duplicate", special),
                card("unit", "scoiatael_dol_blathanna_archer"),
            ],
            board=rows(close=[card("board", "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            leader_used=True,
            hand=[card("hidden", "neutral_geralt")],
            board=rows(close=[card("enemy", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    if weight == "leader_value":
        state = make_clear_weather_leader_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    actions = enumerate_legal_actions(
        state, card_registry=CARD_REGISTRY, leader_registry=LEADER_REGISTRY
    )
    plans = tuple(
        build_decision_plan(
            observation,
            actions,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            config=replace(
                DEFAULT_BASELINE_CONFIG,
                weights=replace(DEFAULT_BASELINE_CONFIG.weights, **{weight: value}),
            ),
        )
        for value in (0.0, endpoint)
    )
    before = {item.action: item.total for item in plans[0].ranked_actions}
    after = {item.action: item.total for item in plans[1].ranked_actions}
    deltas = tuple(after[action] - before[action] for action in before.keys() & after.keys())
    assert max(deltas) - min(deltas) > 1e-9
    assert all(plan.chosen_action in actions for plan in plans)
