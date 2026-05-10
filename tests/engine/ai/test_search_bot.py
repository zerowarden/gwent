from __future__ import annotations

from dataclasses import replace

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.search import (
    DEFAULT_SEARCH_CONFIG,
    SearchBot,
    SearchConfig,
    SearchDecisionExplanation,
    build_search_engine,
)
from gwent_engine.ai.search.depth_policy import should_search_opponent_reply
from gwent_engine.ai.search.opponent_model import generate_opponent_reply_candidates
from gwent_engine.ai.search.public_info import redact_private_information
from gwent_engine.ai.search.types import SearchResult
from gwent_engine.core import ChoiceSourceKind, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction, ResolveChoiceAction
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.core.state import GameState

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
    NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_search_engine_resolves_same_turn_medic_choice_in_principal_line() -> None:
    state = (
        scenario("search_medic_full_turn")
        .player(
            "p1",
            hand=[
                card("p1_medic", "nilfgaard_etolian_auxilary_archer"),
                card("p1_small_archer", "scoiatael_dol_blathanna_archer"),
            ],
            discard=[
                card("p1_discard_large", "northern_realms_catapult"),
            ],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_unit", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.used_fallback_policy is False
    assert result.principal_line is not None
    assert result.principal_line.actions[0] == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_medic"),
        target_row=Row.RANGED,
    )
    second_action = result.principal_line.actions[1]
    assert isinstance(second_action, ResolveChoiceAction)
    assert second_action.player_id == PLAYER_ONE_ID
    assert second_action.selected_card_instance_ids == (CardInstanceId("p1_discard_large"),)
    assert result.chosen_action == result.principal_line.actions[0]
    assert result.principal_line.reply_actions == ()


def test_search_engine_falls_back_without_engine_state() -> None:
    state = (
        scenario("search_fallback_without_state")
        .player(
            "p1",
            hand=[
                card("p1_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )
    observation = replace(build_player_observation(state, PLAYER_ONE_ID), engine_state=None)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.used_fallback_policy is True
    assert result.principal_line is None
    assert "reason=missing_engine_state" in result.notes


def test_search_bot_pending_choice_uses_search_line_when_state_is_present() -> None:
    state = (
        scenario("search_pending_choice_state")
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
    bot = SearchBot()

    selected = bot.choose_pending_choice(
        build_player_observation(state, PLAYER_ONE_ID),
        enumerate_legal_actions(
            state,
            player_id=PLAYER_ONE_ID,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert selected.player_id == PLAYER_ONE_ID
    assert selected.selected_card_instance_ids == (CardInstanceId("p1_spy_target"),)


def test_search_engine_avoids_public_leader_reply_trap() -> None:
    state = (
        scenario("search_public_leader_reply_trap")
        .player(
            "p1",
            hand=[
                card("p1_catapult", "northern_realms_catapult"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .build()
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.used_fallback_policy is False
    assert result.chosen_action == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_defender"),
        target_row=Row.CLOSE,
    )


def test_search_engine_skips_reply_search_when_opponent_has_passed() -> None:
    state = (
        scenario("search_skip_reply_opponent_passed")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            passed=True,
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
        )
        .build()
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.principal_line is not None
    assert result.principal_line.reply_actions == ()
    assert any(
        note in {"reply_search=opponent_already_passed", "reply_search=control_not_with_opponent"}
        for note in result.principal_line.notes
    )


def test_generate_opponent_reply_candidates_adds_inferred_hidden_pressure() -> None:
    state = (
        scenario("search_inferred_hidden_pressure")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            hand=[
                card("p2_hidden_a", "scoiatael_mahakaman_defender"),
                card("p2_hidden_b", "scoiatael_dol_blathanna_archer"),
                card("p2_hidden_c", "northern_realms_trebuchet"),
            ],
        )
        .current_player("p2")
        .build()
    )

    candidates = generate_opponent_reply_candidates(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(candidate.reason == "inferred_hidden_hand_pressure" for candidate in candidates)
    inferred = next(
        candidate for candidate in candidates if candidate.reason == "inferred_hidden_hand_pressure"
    )
    assert inferred.action is None
    assert inferred.inferred_penalty > 0


def test_generate_opponent_reply_candidates_respect_hidden_pressure_config() -> None:
    state = (
        scenario("search_inferred_hidden_pressure_tuning")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            hand=[
                card("p2_hidden_a", "scoiatael_mahakaman_defender"),
                card("p2_hidden_b", "scoiatael_dol_blathanna_archer"),
                card("p2_hidden_c", "northern_realms_trebuchet"),
            ],
        )
        .current_player("p2")
        .build()
    )

    default_inferred = next(
        candidate
        for candidate in generate_opponent_reply_candidates(
            state,
            viewer_player_id=PLAYER_ONE_ID,
            profile_definition=DEFAULT_BASE_PROFILE,
            config=DEFAULT_SEARCH_CONFIG,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        if candidate.reason == "inferred_hidden_hand_pressure"
    )
    reduced_inferred = next(
        candidate
        for candidate in generate_opponent_reply_candidates(
            state,
            viewer_player_id=PLAYER_ONE_ID,
            profile_definition=DEFAULT_BASE_PROFILE,
            config=SearchConfig(
                hidden_reply_unused_leader_bonus=0.0,
                hidden_reply_hand_parity_bonus=0.0,
            ),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        if candidate.reason == "inferred_hidden_hand_pressure"
    )

    assert default_inferred.inferred_penalty > reduced_inferred.inferred_penalty


def test_search_engine_prefers_final_round_decoy_reclaim_spy_over_pass() -> None:
    state = (
        scenario("search_final_round_decoy_reclaim_spy")
        .round(3)
        .player(
            "p1",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            hand=[
                card("p1_decoy", "neutral_decoy"),
                card("p1_cow", "neutral_avenger_cow"),
            ],
            deck=[
                card("p1_deck_geralt", "neutral_geralt"),
                card("p1_deck_scorpion", "nilfgaard_heavy_zerrikanian_fire_scorpion"),
                card("p1_deck_vill", "neutral_villentretenmerth"),
                card("p1_deck_archer", "nilfgaard_black_infantry_archer"),
            ],
            board=rows(
                close=[
                    card(
                        "p1_board_enemy_spy",
                        "nilfgaard_shilard_fitz_oesterlen",
                        owner="p2",
                    )
                ]
            ),
        )
        .player(
            "p2",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            hand=[card("p2_hidden_finisher", "neutral_geralt")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    explanation = engine.explain_result(result)
    decoy_action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_decoy"),
    )
    decoy_evaluation = next(
        evaluation for evaluation in explanation.evaluations if evaluation.action == decoy_action
    )
    pass_evaluation = next(
        evaluation
        for evaluation in explanation.evaluations
        if isinstance(evaluation.action, PassAction)
    )

    assert decoy_evaluation.line.value > pass_evaluation.line.value
    assert "root_adjustment=elimination_pass_with_live_lines" in pass_evaluation.line.notes
    assert not isinstance(result.chosen_action, PassAction)


def test_generate_opponent_reply_candidates_caps_pending_choice_replies() -> None:
    state = (
        scenario("search_reply_cap_pending_choice")
        .player(
            "p1",
            hand=[card("p1_decoy_source", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("p1_target_a", "neutral_mysterious_elf", owner="p2"),
                    card("p1_target_b", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .card_choice(
            choice_id="pending_choice_1",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=("p1_target_a", "p1_target_b"),
        )
        .current_player("p1")
        .build()
    )

    candidates = generate_opponent_reply_candidates(
        state,
        viewer_player_id=PLAYER_TWO_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=SearchConfig(max_opponent_replies=1),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert len(candidates) == 1


def test_reply_depth_policy_triggers_for_close_score_gap() -> None:
    state = (
        scenario("search_reply_policy_close_gap")
        .player("p1", board=rows(close=[card("p1_archer", "scoiatael_dol_blathanna_archer")]))
        .player("p2", hand=[card("p2_hidden", "scoiatael_mahakaman_defender")])
        .current_player("p2")
        .build()
    )

    decision = should_search_opponent_reply(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert decision.enabled is True
    assert decision.reason in {"close_score_gap", "opponent_hidden_pressure"}


def test_redact_private_information_replaces_only_opponent_hidden_zones() -> None:
    state = (
        scenario("search_public_redaction")
        .player(
            "p1",
            hand=[card("p1_known_archer", "scoiatael_dol_blathanna_archer")],
            deck=[card("p1_known_deck", "northern_realms_trebuchet")],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_hand", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
            discard=[card("p2_public_discard", "scoiatael_mahakaman_defender")],
            board=rows(ranged=[card("p2_public_board", "northern_realms_trebuchet")]),
        )
        .build()
    )

    redacted = redact_private_information(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert redacted.card(CardInstanceId("p1_known_archer")).definition_id == CardDefinitionId(
        "scoiatael_dol_blathanna_archer"
    )
    assert redacted.card(CardInstanceId("p1_known_deck")).definition_id == CardDefinitionId(
        "northern_realms_trebuchet"
    )
    assert redacted.card(CardInstanceId("p2_hidden_hand")).zone == Zone.HAND
    assert redacted.card(CardInstanceId("p2_hidden_deck")).zone == Zone.DECK
    assert redacted.card(CardInstanceId("p2_hidden_hand")).definition_id == (
        redacted.card(CardInstanceId("p2_hidden_deck")).definition_id
    )
    assert redacted.card(CardInstanceId("p2_public_discard")).definition_id == (
        CardDefinitionId("scoiatael_mahakaman_defender")
    )
    assert redacted.card(CardInstanceId("p2_public_board")).definition_id == (
        CardDefinitionId("northern_realms_trebuchet")
    )


def test_search_engine_ignores_opponent_hidden_hand_and_deck_identities() -> None:
    state_a = (
        scenario("search_public_info_invariance")
        .player(
            "p1",
            hand=[
                card("p1_catapult", "northern_realms_catapult"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            hand=[card("p2_hidden_a", "neutral_geralt")],
            deck=[card("p2_deck_a", "northern_realms_catapult")],
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .build()
    )
    state_b = (
        scenario("search_public_info_invariance_alt")
        .player(
            "p1",
            hand=[
                card("p1_catapult", "northern_realms_catapult"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            hand=[card("p2_hidden_other", "neutral_mysterious_elf")],
            deck=[card("p2_deck_other", "skellige_kambi")],
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .build()
    )

    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    def choose(state_name: str, state_obj: GameState) -> SearchResult:
        observation = build_player_observation(state_obj, PLAYER_ONE_ID, LEADER_REGISTRY)
        legal_actions = enumerate_legal_actions(
            state_obj,
            player_id=PLAYER_ONE_ID,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        result = engine.choose_action(
            observation,
            legal_actions,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        assert result.principal_line is not None, state_name
        return result

    result_a = choose("state_a", state_a)
    result_b = choose("state_b", state_b)

    assert result_a.chosen_action == result_b.chosen_action
    assert result_a.principal_line is not None
    assert result_b.principal_line is not None
    assert result_a.principal_line.reply_actions == result_b.principal_line.reply_actions


def test_generate_opponent_reply_candidates_do_not_exact_search_hidden_pending_choice() -> None:
    state = (
        scenario("search_hidden_pending_choice_redacted")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            faction="monsters",
            leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            hand=[card("p2_hidden_hand", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .pending_choice(
            choice_id="hidden_leader_choice",
            player_id="p2",
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            legal_target_card_instance_ids=("p2_hidden_hand", "p2_hidden_deck"),
            min_selections=2,
            max_selections=2,
        )
        .current_player("p2")
        .build()
    )

    candidates = generate_opponent_reply_candidates(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert candidates
    assert all(candidate.action is None for candidate in candidates)
    assert {candidate.reason for candidate in candidates} == {"inferred_hidden_pending_choice"}


def test_generate_opponent_reply_candidates_respect_hidden_pending_choice_bonus() -> None:
    state = (
        scenario("search_hidden_pending_choice_tuning")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            faction="monsters",
            leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            hand=[card("p2_hidden_hand", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .pending_choice(
            choice_id="hidden_leader_choice_tuning",
            player_id="p2",
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            legal_target_card_instance_ids=("p2_hidden_hand", "p2_hidden_deck"),
            min_selections=2,
            max_selections=2,
        )
        .current_player("p2")
        .build()
    )

    default_inferred = generate_opponent_reply_candidates(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )[0]
    boosted_inferred = generate_opponent_reply_candidates(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=SearchConfig(hidden_pending_choice_bonus=9.0),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )[0]

    assert default_inferred.reason == "inferred_hidden_pending_choice"
    assert boosted_inferred.reason == "inferred_hidden_pending_choice"
    assert boosted_inferred.inferred_penalty > default_inferred.inferred_penalty


def test_search_engine_explanation_includes_evaluated_lines() -> None:
    state = (
        scenario("search_explanation_evaluated_lines")
        .player(
            "p1",
            hand=[
                card("p1_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
        )
        .player(
            "p2",
            hand=[card("p2_hidden", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    explanation = engine.explain_result(result)

    assert isinstance(explanation, SearchDecisionExplanation)
    assert explanation.profile_id == "baseline"
    assert explanation.evaluations
    assert explanation.principal_line is not None
    assert explanation.principal_line.explanation.leaf_terms
    assert any(item.selected for item in explanation.evaluations)
    assert explanation.comparison is not None
    assert explanation.comparison.chosen_action == result.chosen_action


def test_search_engine_respects_leaf_value_scales() -> None:
    state = (
        scenario("search_leaf_value_scales")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            hand=[card("p2_hidden", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    default_engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_default",
    )
    weighted_engine = build_search_engine(
        config=SearchConfig(
            score_gap_scale=2.0,
            card_advantage_scale=0.5,
            hand_value_scale=0.5,
            leader_delta_scale=0.5,
            exact_finish_bonus_scale=2.0,
        ),
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_weighted",
    )

    default_result = default_engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    weighted_result = weighted_engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert default_result.principal_line is not None
    assert weighted_result.principal_line is not None
    assert default_result.principal_line.value != weighted_result.principal_line.value
