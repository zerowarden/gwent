from __future__ import annotations

from dataclasses import replace

import pytest
from gwent_engine.ai.actions import enumerate_legal_actions, filter_non_leave_actions
from gwent_engine.ai.baseline import DEFAULT_BASELINE_CONFIG, HeuristicBot
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.context import classify_context
from gwent_engine.ai.baseline.decision_plan import DecisionPlan, build_decision_plan
from gwent_engine.ai.baseline.evaluation import explain_action_score
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfigurationError
from gwent_engine.ai.baseline.profiles import compose_profile
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.turn_actions import enumerate_mulligan_selections
from gwent_engine.core import GameStatus, Phase, Row
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action

from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    build_sample_game_state,
    build_started_game_state,
    choose_bot_response,
)
from ..support import (
    make_clear_weather_leader_state,
    make_steel_forged_noop_state,
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
            hand=[card("p1_reserve_weather", "neutral_clear_weather")],
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
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
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


def _ranking_scope_plans(*scopes: str) -> tuple[tuple[GameAction, ...], tuple[DecisionPlan, ...]]:
    units = (
        "northern_realms_catapult",
        "northern_realms_ballista",
        "northern_realms_siege_tower",
        "northern_realms_trebuchet",
        "northern_realms_keira_metz",
        "northern_realms_sile_de_tansarville",
        "northern_realms_dun_banner_medic",
        "northern_realms_prince_stennis",
    )
    state = (
        scenario("ranking_scope_with_cheap_spy")
        .player(
            "p1",
            faction="northern_realms",
            hand=[
                *(card(f"p1_unit_{index}", unit) for index, unit in enumerate(units)),
                card("p1_cheap_spy", "northern_realms_thaler"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY
    )
    plans = tuple(
        build_decision_plan(
            observation,
            legal_actions,
            card_registry=CARD_REGISTRY,
            config=replace(
                DEFAULT_BASELINE_CONFIG,
                candidates=replace(DEFAULT_BASELINE_CONFIG.candidates, ranking_scope=scope),
            ),
        )
        for scope in scopes
    )
    return legal_actions, plans


def test_all_legal_ranking_scope_weighs_actions_the_shortlist_cuts() -> None:
    legal_actions, (shortlist, all_legal) = _ranking_scope_plans("shortlist", "all_legal")
    cheap_spy = CardInstanceId("p1_cheap_spy")

    def ranked_cards(plan: DecisionPlan) -> set[CardInstanceId | None]:
        return {
            breakdown.action.card_instance_id
            for breakdown in plan.ranked_actions
            if isinstance(breakdown.action, PlayCardAction)
        }

    assert cheap_spy not in ranked_cards(shortlist)
    assert cheap_spy in ranked_cards(all_legal)
    assert len(all_legal.ranked_actions) == len(filter_non_leave_actions(legal_actions))
    assert all_legal.all_candidates == shortlist.all_candidates


def test_default_ranking_scope_is_the_shortlist() -> None:
    _, (default, shortlist) = _ranking_scope_plans(
        DEFAULT_BASELINE_CONFIG.candidates.ranking_scope, "shortlist"
    )

    assert default == shortlist
    assert len(default.ranked_actions) == DEFAULT_BASELINE_CONFIG.candidates.max_candidates


def test_unknown_ranking_scope_is_rejected() -> None:
    config = replace(
        DEFAULT_BASELINE_CONFIG,
        candidates=replace(DEFAULT_BASELINE_CONFIG.candidates, ranking_scope="everything"),
    )

    with pytest.raises(HeuristicConfigurationError, match="ranking_scope"):
        _ = HeuristicBot(config=config)
