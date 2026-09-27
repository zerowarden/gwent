from __future__ import annotations

import json
import math
import subprocess
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace
from typing import cast

import pytest
from gwent_engine.ai import heuristic_configuration as heuristic_configuration_module
from gwent_engine.ai.actions import enumerate_mulligan_selections
from gwent_engine.ai.arena import bot_family, create_bot, create_seeded_bot
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.baseline import bot as bot_module
from gwent_engine.ai.baseline.decision_plan import DecisionPlan, build_decision_plan
from gwent_engine.ai.baseline.profile_catalog import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    get_base_profile_definition,
)
from gwent_engine.ai.heuristic_configuration import (
    HeuristicConfiguration,
    HeuristicConfigurationError,
)
from gwent_engine.ai.observations import PlayerObservation, build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, BaselineConfig, EvaluationWeights
from gwent_engine.cards import CardRegistry
from gwent_engine.core import ChoiceSourceKind
from gwent_engine.core.actions import GameAction
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    build_started_game_state,
    choose_bot_response,
)
from .support import (
    make_opponent_passed_guaranteed_win_state,
    make_round_three_visible_win_state,
)


def _candidate(**weights: float) -> HeuristicConfiguration:
    return HeuristicConfiguration(
        baseline=replace(
            DEFAULT_BASELINE_CONFIG, weights=replace(DEFAULT_BASELINE_CONFIG.weights, **weights)
        )
    )


def _bot(configuration: HeuristicConfiguration) -> HeuristicBot:
    bot = create_bot("heuristic", bot_id="candidate", heuristic_configuration=configuration)
    assert isinstance(bot, HeuristicBot)
    return bot


def _opening_state() -> GameState:
    return (
        scenario("configuration_opening")
        .player(
            "p1",
            hand=[
                card("archer", "scoiatael_dol_blathanna_archer"),
                card("hero", "neutral_geralt"),
                card("archer2", "scoiatael_dol_blathanna_archer"),
            ],
            board=rows(close=[card("defender", "scoiatael_mahakaman_defender")]),
        )
        .player("p2", hand=[card("hidden", "neutral_geralt")])
        .build()
    )


def _capture_plan(
    monkeypatch: pytest.MonkeyPatch, bot: HeuristicBot, state: GameState
) -> DecisionPlan:
    plans: list[DecisionPlan] = []

    def capture(
        observation: PlayerObservation,
        legal_actions: tuple[GameAction, ...],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None,
        config: BaselineConfig,
        profile_definition: BaseProfileDefinition,
    ) -> DecisionPlan:
        plan = build_decision_plan(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
            config=config,
            profile_definition=profile_definition,
        )
        plans.append(plan)
        return plan

    monkeypatch.setattr(bot_module, "build_decision_plan", capture)
    chosen = choose_bot_response(
        bot,
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    assert len(plans) == 1
    assert chosen == plans[0].chosen_action
    assert chosen in plans[0].legal_actions
    return plans[0]


def test_candidates_are_isolated_from_each_other_and_named_defaults() -> None:
    default = HeuristicConfiguration()
    first = _candidate(immediate_points=3.125)
    second = _candidate(card_advantage=7.25)
    first_bot, second_bot = _bot(first), _bot(second)
    changed = replace(first, baseline=replace(first.baseline, weights=EvaluationWeights()))
    assert changed == default
    assert first_bot.configuration == first
    assert second_bot.configuration == second
    assert _bot(default).configuration == default
    assert DEFAULT_BASELINE_CONFIG == BaselineConfig()
    assert get_base_profile_definition("neutral") == DEFAULT_BASE_PROFILE
    assert bot_family("heuristic").fixed_configuration["baseline"] is DEFAULT_BASELINE_CONFIG
    for record, name, value in [
        (first.baseline.weights, "immediate_points", 99.0),
        (first, "baseline", second.baseline),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(record, name, value)


@pytest.mark.parametrize("name", [field.name for field in fields(EvaluationWeights)])
def test_every_weight_reaches_the_actual_bot_decision_plan(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    config = _candidate(**{name: 3.125})
    plan = _capture_plan(monkeypatch, _bot(config), _opening_state())
    provenance = next(item for item in plan.profile.weight_provenance if item.name == name)
    assert provenance.base_config == 3.125
    assert provenance.profile_override is None
    expected = 3.125
    for adjustment in provenance.adjustments:
        expected *= adjustment.factor
    assert provenance.resolved == expected
    assert getattr(plan.profile.weights, name) == expected
    if name not in {"leader_value", "exact_finish_bonus"}:
        terms = [
            term
            for action in plan.ranked_actions
            for term in action.terms
            if term.weight_label in {name, f"{name}_weight"}
        ]
        assert terms
        assert all(term.weight == expected for term in terms)


@pytest.mark.parametrize(
    "state_factory, field_name, expected, term_name",
    [
        (_opening_state, "card_advantage", 4.5, "card_advantage"),
        (_opening_state, "remaining_hand_value", 4.5, "post_action_hand_value"),
        (
            make_opponent_passed_guaranteed_win_state,
            "immediate_points",
            4.5,
            "projected_net_board_swing",
        ),
        (
            make_opponent_passed_guaranteed_win_state,
            "overcommit_penalty",
            6.75,
            "overcommit_penalty",
        ),
    ],
)
def test_injected_weights_keep_contextual_multipliers_in_score_terms(
    monkeypatch: pytest.MonkeyPatch,
    state_factory: Callable[[], GameState],
    field_name: str,
    expected: float,
    term_name: str,
) -> None:
    plan = _capture_plan(monkeypatch, _bot(_candidate(**{field_name: 3.0})), state_factory())
    terms = [
        term for action in plan.ranked_actions for term in action.terms if term.name == term_name
    ]
    assert terms
    assert all(term.weight == expected for term in terms)
    assert any(term.raw_value != 0 for term in terms)
    for term in terms:
        assert term.raw_value is not None
        assert math.isclose(term.value, term.raw_value * expected)


def test_leader_and_exact_finish_weights_reach_constant_score_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leader_plan = _capture_plan(monkeypatch, _bot(_candidate(leader_value=3.0)), _opening_state())
    reserve_costs = [
        term.value
        for action in leader_plan.ranked_actions
        for term in action.terms
        if term.name == "leader_reserve_cost"
    ]
    assert reserve_costs and all(math.isclose(value, -15.84) for value in reserve_costs)
    secured = (
        scenario("configuration_secured_lead")
        .player(
            "p1",
            hand=[card("reserve", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("hero", "neutral_geralt")]),
        )
        .player("p2", passed=True)
        .build()
    )
    finish_plan = _capture_plan(
        monkeypatch,
        _bot(_candidate(exact_finish_bonus=3.0)),
        secured,
    )
    assert any(
        term.name == "pass_exact_finish_bonus" and term.value == 6.75
        for action in finish_plan.ranked_actions
        for term in action.terms
    )


@pytest.mark.parametrize("profile_id", ["neutral", "conservative", "aggressive"])
@pytest.mark.parametrize(
    "state_factory",
    [_opening_state, make_opponent_passed_guaranteed_win_state, make_round_three_visible_win_state],
)
def test_named_and_materialized_configurations_make_the_same_decisions(
    profile_id: str, state_factory: Callable[[], GameState]
) -> None:
    explicit = HeuristicConfiguration.from_profile_id(profile_id)
    named = create_bot(f"heuristic:{profile_id}", bot_id="named")
    assert isinstance(named, HeuristicBot)
    assert named.configuration == explicit
    assert named.configuration.digest() == explicit.digest()
    state = state_factory()
    assert choose_bot_response(
        named, state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY
    ) == choose_bot_response(
        _bot(explicit), state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY
    )


def test_explicit_profile_is_not_resolved_again_and_overrides_still_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = replace(
        DEFAULT_BASE_PROFILE,
        profile_id="unregistered",
        weights=replace(DEFAULT_BASE_PROFILE.weights, card_advantage=5.0),
    )
    config = replace(_candidate(card_advantage=7.0), profile=profile)
    bot = bot_family("heuristic").build_resolved(bot_id="trial", heuristic_configuration=config)
    assert isinstance(bot, HeuristicBot)
    plan = _capture_plan(monkeypatch, bot, _opening_state())
    provenance = next(
        item for item in plan.profile.weight_provenance if item.name == "card_advantage"
    )
    assert provenance.base_config == 7.0
    assert provenance.profile_override == 5.0
    assert provenance.resolved == 7.5
    assert bot.configuration.profile == profile


def test_full_snapshot_round_trip_and_display_name_independent_digest() -> None:
    default = HeuristicConfiguration.from_profile_id("aggressive")
    config = replace(
        default,
        baseline=replace(
            default.baseline,
            weights=replace(default.baseline.weights, immediate_points=1.2345678901234567),
            action_bonus=replace(default.baseline.action_bonus, spy_bonus=11.0),
            candidates=replace(
                default.baseline.candidates, max_candidates=12, always_keep_pass=False
            ),
            candidate_scoring=replace(default.baseline.candidate_scoring, pass_score=-7.0),
            pass_logic=replace(default.baseline.pass_logic, safe_lead_margin=8),
            profile_tuning=replace(default.baseline.profile_tuning, economy_weight_multiplier=1.2),
        ),
    )
    decoded = HeuristicConfiguration.from_json(json.dumps(config.to_dict()))
    assert decoded == config
    assert decoded.digest() == config.digest()
    assert (
        decoded.baseline.weights.immediate_points.hex()
        == config.baseline.weights.immediate_points.hex()
    )
    renamed = replace(config, profile=replace(config.profile, profile_id="display-label"))
    assert renamed.to_dict() != config.to_dict()
    assert renamed.digest() == config.digest()


def test_numeric_normalization_including_optional_overrides_and_signed_zero() -> None:
    python = replace(
        _candidate(immediate_points=2, card_advantage=-0.0),
        profile=replace(
            DEFAULT_BASE_PROFILE, weights=replace(DEFAULT_BASE_PROFILE.weights, leader_value=4)
        ),
    )
    decoded = HeuristicConfiguration.from_json(json.dumps(python.to_dict()))
    assert decoded == python
    assert type(python.baseline.weights.immediate_points) is float
    assert type(python.profile.weights.leader_value) is float
    assert python.baseline.weights.card_advantage.hex() == (0.0).hex()
    positive_zero = replace(
        python,
        baseline=replace(
            python.baseline, weights=replace(python.baseline.weights, card_advantage=0.0)
        ),
    )
    assert positive_zero.digest() == python.digest()


@pytest.mark.parametrize("name", [field.name for field in fields(EvaluationWeights)])
@pytest.mark.parametrize("value", [True, "2.0", None, float("nan"), float("inf"), -float("inf")])
def test_invalid_weights_are_rejected_in_python_and_payloads(name: str, value: object) -> None:
    with pytest.raises(HeuristicConfigurationError, match=name):
        _ = _candidate(**{name: cast(float, value)})
    payload = HeuristicConfiguration().to_dict()
    baseline = cast(dict[str, object], payload["baseline"])
    cast(dict[str, object], baseline["weights"])[name] = value
    with pytest.raises(HeuristicConfigurationError):
        _ = HeuristicConfiguration.from_json(json.dumps(payload))


@pytest.mark.parametrize(
    "section, name, value",
    [
        ("action_bonus", "spy_bonus", True),
        ("candidate_scoring", "pass_score", float("inf")),
        ("candidates", "max_candidates", True),
        ("candidates", "max_candidates", 6.0),
        ("candidates", "always_keep_pass", 1),
        ("pass_logic", "safe_lead_margin", "6"),
        ("profile_tuning", "economy_weight_multiplier", float("nan")),
    ],
)
def test_invalid_fixed_fields_are_rejected_on_both_paths(
    section: str, name: str, value: object
) -> None:
    component = {
        "action_bonus": DEFAULT_BASELINE_CONFIG.action_bonus,
        "candidate_scoring": DEFAULT_BASELINE_CONFIG.candidate_scoring,
        "candidates": DEFAULT_BASELINE_CONFIG.candidates,
        "pass_logic": DEFAULT_BASELINE_CONFIG.pass_logic,
        "profile_tuning": DEFAULT_BASELINE_CONFIG.profile_tuning,
    }[section]
    with pytest.raises(HeuristicConfigurationError):
        _ = HeuristicConfiguration(
            baseline=replace(
                DEFAULT_BASELINE_CONFIG, **{section: replace(component, **{name: value})}
            )
        )
    payload = HeuristicConfiguration().to_dict()
    baseline = cast(dict[str, object], payload["baseline"])
    cast(dict[str, object], baseline[section])[name] = value
    with pytest.raises(HeuristicConfigurationError):
        _ = HeuristicConfiguration.from_dict(payload)


def test_malformed_nested_records_and_unknown_policies_are_rejected() -> None:
    with pytest.raises(HeuristicConfigurationError, match="BaselineConfig"):
        _ = HeuristicConfiguration(baseline=cast(BaselineConfig, object()))
    with pytest.raises(HeuristicConfigurationError, match="EvaluationWeights"):
        _ = HeuristicConfiguration(
            baseline=replace(DEFAULT_BASELINE_CONFIG, weights=cast(EvaluationWeights, object()))
        )
    malformed_profiles = [
        replace(DEFAULT_BASE_PROFILE, profile_id=" "),
        replace(
            DEFAULT_BASE_PROFILE, policies=replace(DEFAULT_BASE_PROFILE.policies, leader="unknown")
        ),
        replace(
            DEFAULT_BASE_PROFILE,
            weights=replace(DEFAULT_BASE_PROFILE.weights, immediate_points=True),
        ),
        replace(
            DEFAULT_BASE_PROFILE,
            pass_overrides=replace(DEFAULT_BASE_PROFILE.pass_overrides, safe_lead_margin=True),
        ),
    ]
    for profile in malformed_profiles:
        with pytest.raises(HeuristicConfigurationError):
            _ = HeuristicConfiguration(profile=profile)


def test_unsupported_field_annotation_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = HeuristicConfiguration().to_dict()
    field_types = dict(
        heuristic_configuration_module._FIELD_TYPES[EvaluationWeights]  # pyright: ignore[reportPrivateUsage]
    )
    field_types["immediate_points"] = complex
    monkeypatch.setitem(
        heuristic_configuration_module._FIELD_TYPES,  # pyright: ignore[reportPrivateUsage]
        EvaluationWeights,
        field_types,
    )
    with pytest.raises(HeuristicConfigurationError, match="Unsupported configuration field type"):
        _ = HeuristicConfiguration.from_dict(payload)


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("baseline",),
        ("baseline", "weights"),
        ("profile",),
        ("profile", "policies"),
        ("profile", "weights"),
        ("profile", "pass_overrides"),
    ],
)
@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_snapshot_rejects_unknown_and_missing_fields(path: tuple[str, ...], mutation: str) -> None:
    payload = HeuristicConfiguration().to_dict()
    mapping = payload
    for key in path:
        mapping = cast(dict[str, object], mapping[key])
    if mutation == "unknown":
        mapping["unknown"] = 1
    else:
        del mapping[next(iter(mapping))]
    with pytest.raises(HeuristicConfigurationError, match=f"{mutation} fields"):
        _ = HeuristicConfiguration.from_dict(payload)


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(HeuristicConfigurationError, match="duplicate key"):
        _ = HeuristicConfiguration.from_json('{"baseline": {}, "baseline": {}}')


@pytest.mark.parametrize("family", ["random", "greedy", "search"])
def test_explicit_configuration_only_supported_for_heuristic(family: str) -> None:
    with pytest.raises(ValueError, match="does not accept a heuristic configuration"):
        _ = create_bot(family, bot_id="bad", heuristic_configuration=HeuristicConfiguration())


def test_factory_rejects_ambiguous_or_untyped_configuration() -> None:
    with pytest.raises(ValueError, match="not both"):
        _ = create_bot(
            "heuristic:neutral", bot_id="bad", heuristic_configuration=HeuristicConfiguration()
        )
    with pytest.raises(ValueError, match="not both"):
        _ = bot_family("heuristic").build_resolved(
            bot_id="bad",
            profile=DEFAULT_BASE_PROFILE,
            heuristic_configuration=HeuristicConfiguration(),
        )
    with pytest.raises(ValueError, match="typed HeuristicConfiguration"):
        _ = create_bot(
            "heuristic",
            bot_id="bad",
            heuristic_configuration=cast(HeuristicConfiguration, object()),
        )
    with pytest.raises(ValueError, match="does not accept a seed"):
        _ = create_bot(
            "heuristic", bot_id="bad", seed=1, heuristic_configuration=HeuristicConfiguration()
        )
    bot = create_seeded_bot(
        "heuristic",
        bot_id="candidate",
        seed=1,
        heuristic_configuration=_candidate(immediate_points=3.0),
    )
    assert isinstance(bot, HeuristicBot)
    assert bot.configuration == _candidate(immediate_points=3.0)


def test_action_weights_do_not_change_mulligan_or_pending_choice() -> None:
    default = _bot(HeuristicConfiguration())
    candidate = _bot(_candidate(**{field.name: 123.0 for field in fields(EvaluationWeights)}))
    state, _ = build_started_game_state()
    observation = build_player_observation(state, PLAYER_ONE_ID)
    selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)
    assert default.choose_mulligan(
        observation, selections, card_registry=CARD_REGISTRY
    ) == candidate.choose_mulligan(observation, selections, card_registry=CARD_REGISTRY)
    pending_state = (
        scenario("configuration_pending")
        .player(
            "p1",
            hand=[card("source_decoy", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("spy", "neutral_mysterious_elf", owner="p2"),
                    card("archer", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .card_choice(
            choice_id="decoy",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="source_decoy",
            legal_target_card_instance_ids=("spy", "archer"),
        )
        .build()
    )
    assert choose_bot_response(
        default,
        pending_state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        pending_choice=True,
    ) == choose_bot_response(
        candidate,
        pending_state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        pending_choice=True,
    )


def test_fresh_process_runtime_construction_does_not_import_optimization() -> None:
    code = """
import sys
from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.arena import create_bot
create_bot('heuristic', bot_id='runtime', heuristic_configuration=HeuristicConfiguration())
assert not any(
    name == 'cma' or name.startswith(('cma.', 'gwent_evaluation')) for name in sys.modules
)
"""
    _ = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
