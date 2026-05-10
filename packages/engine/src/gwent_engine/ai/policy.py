"""Central catalogue for hand-tuned AI numbers.

Rules code should stay deterministic and policy-free. AI code can still use
hand-tuned values, but those values should live here instead of being embedded
as anonymous literals at call sites. The grouping mirrors a Rust-style enum
boundary: each dataclass is one named policy variant/family, and the
`AIHandTunedPolicy` root makes the full tuned surface easy to audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gwent_engine.core import AbilityKind

OPPORTUNISTIC_SCORCH_POLICY_ID = "opportunistic_scorch"
RESERVE_SCORCH_POLICY_ID = "reserve_scorch"
CONSERVATIVE_LEADER_POLICY_ID = "conservative"
AGGRESSIVE_LEADER_POLICY_ID = "aggressive"
LEGACY_PRESERVE_LEADER_POLICY_ID = "preserve_leader"
LEGACY_TEMPO_LEADER_POLICY_ID = "tempo_leader"


@dataclass(frozen=True, slots=True)
class PolicySelection:
    """Named policy ids chosen for one heuristic profile."""

    scorch: str
    leader: str

    @property
    def scorch_policy(self) -> str:
        return self.scorch

    @property
    def leader_policy(self) -> str:
        return self.leader


@dataclass(frozen=True, slots=True)
class PolicyResourceBias:
    """Resolved resource-bias inputs consumed by policy evaluators."""

    minimum_commitment: float
    preserve_resources: float


@dataclass(frozen=True, slots=True)
class EvaluationWeights:
    """Weights for generic baseline action score terms."""

    immediate_points: float = 1.0
    card_advantage: float = 2.0
    remaining_hand_value: float = 0.25
    leader_value: float = 4.0
    scorch_exposure: float = -1.5
    weather_exposure: float = -1.0
    horn_potential: float = 0.6
    synergy_retention: float = 1.0
    overcommit_penalty: float = -1.0
    dead_card_penalty: float = -1.0
    exact_finish_bonus: float = 4.0


@dataclass(frozen=True, slots=True)
class ActionBonusConfig:
    """Action-family-specific baseline bonuses and penalties."""

    leave_penalty: float = -1000.0
    unsupported_action_penalty: float = -1.0
    scorch_bonus: float = 4.0
    scorch_no_live_targets_penalty: float = -14.0
    scorch_self_damage_penalty: float = -12.0
    decoy_bonus: float = 3.0
    decoy_target_strength_bonus: float = 0.5
    decoy_spy_reclaim_bonus: float = 8.0
    decoy_scorch_save_bonus: float = 6.0
    spy_bonus: float = 6.0
    medic_bonus: float = 4.0
    weather_no_swing_penalty: float = -6.0
    invalid_target_penalty: float = -8.0
    horn_no_valid_targets_penalty: float = -12.0
    horn_target_count_bonus: float = 1.0
    horn_valid_strength_delta_bonus: float = 1.0
    horn_setup_penalty: float = 6.0


@dataclass(frozen=True, slots=True)
class CandidateConfig:
    """Root candidate retention policy before detailed action evaluation."""

    max_candidates: int = 6
    always_keep_pass: bool = True
    always_keep_leader: bool = True
    always_keep_tactical_specials: bool = True


@dataclass(frozen=True, slots=True)
class CandidateScoringConfig:
    """Coarse move-ordering scores used to keep search/evaluation tractable."""

    pass_score: float = -5.0
    unknown_leader_score: float = 9.0
    no_effect_leader_score: float = -4.0
    leader_hand_delta_multiplier: float = 2.0
    high_value_special_score: float = 7.0
    ordinary_special_score: float = 3.0


@dataclass(frozen=True, slots=True)
class PassConfig:
    """Thresholds for deciding whether preserving resources beats contesting."""

    safe_lead_margin: int = 6
    elimination_safe_lead_margin: int = 3
    minimum_finish_buffer: int = 0
    estimated_opponent_tempo_per_card: int = 2
    elimination_estimated_opponent_tempo_per_card: int = 4


@dataclass(frozen=True, slots=True)
class ProfileTuningConfig:
    """Profile-composition multipliers layered on top of base weights."""

    economy_weight_multiplier: float = 1.5
    tempo_weight_multiplier: float = 1.5
    leader_preservation_multiplier: float = 1.1
    minimum_commitment_weight_multiplier: float = 1.5
    opponent_passed_candidate_limit: int = 4
    minimum_commitment_mode_bias: float = 2.0
    neutral_commitment_mode_bias: float = 1.0
    preserve_resources_bias: float = 1.25
    spend_resources_bias: float = 0.9


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    """Complete hand-tuned configuration for the baseline heuristic evaluator."""

    weights: EvaluationWeights = field(default_factory=EvaluationWeights)
    action_bonus: ActionBonusConfig = field(default_factory=ActionBonusConfig)
    candidates: CandidateConfig = field(default_factory=CandidateConfig)
    candidate_scoring: CandidateScoringConfig = field(default_factory=CandidateScoringConfig)
    pass_logic: PassConfig = field(default_factory=PassConfig)
    profile_tuning: ProfileTuningConfig = field(default_factory=ProfileTuningConfig)


@dataclass(frozen=True, slots=True)
class EvaluationPolicyConfig:
    """Secondary baseline evaluation constants that are not simple term weights."""

    leader_live_commitment_bias_multiplier: float = 2.0
    leader_live_commitment_min_divisor: float = 3.0
    hero_overcommit_min_cost: float = 2.0
    hero_overcommit_strength_divisor: float = 2.0
    medic_overcommit_cost: float = 4.0
    spy_overcommit_cost: float = 3.0
    premium_special_overcommit_cost: float = 5.0
    open_round_excess_divisor: float = 2.0


@dataclass(frozen=True, slots=True)
class TacticalValuePolicyConfig:
    """Commitment estimates used when comparing resource expenditure."""

    leader_commitment_value: int = 8


@dataclass(frozen=True, slots=True)
class MulliganScoreWeights:
    """Profile-specific keep/discard biases for ability-bearing hand cards."""

    medic_keep_bonus: int
    tight_bond_keep_bonus: int
    unit_horn_keep_bonus: int = 0


@dataclass(frozen=True, slots=True)
class MulliganPolicyConfig:
    """Shared mulligan scoring constants plus bot-specific weight groups."""

    baseline: MulliganScoreWeights = field(
        default_factory=lambda: MulliganScoreWeights(
            medic_keep_bonus=-5,
            tight_bond_keep_bonus=-3,
            unit_horn_keep_bonus=-2,
        )
    )
    greedy: MulliganScoreWeights = field(
        default_factory=lambda: MulliganScoreWeights(
            medic_keep_bonus=-4,
            tight_bond_keep_bonus=-2,
        )
    )
    hero_keep_bonus: int = -100
    low_strength_anchor: int = 6
    special_card_penalty: int = 2
    duplicate_non_bond_penalty: int = 4
    spy_keep_bonus: int = -6


@dataclass(frozen=True, slots=True)
class PendingChoicePolicyConfig:
    """Tactical values for resolving Decoy, Medic, and leader choices."""

    invalid_leader_selection_penalty: int = -1000
    decoy_target_spy_bonus: int = 20
    decoy_target_medic_bonus: int = 10
    medic_target_spy_draw_bonus: int = 5
    medic_target_spy_max_draws: int = 2
    medic_target_medic_bonus: int = 4


@dataclass(frozen=True, slots=True)
class FeaturePolicyConfig:
    """Shared feature-extraction constants used by evaluation projections."""

    preserved_leader_value: float = 6.0
    scorch_threshold: int = 10


@dataclass(frozen=True, slots=True)
class ProjectionPolicyConfig:
    """One-step projection bonuses for tactical card text."""

    decoy_spy_reclaim_bonus: int = 8
    decoy_medic_reclaim_bonus: int = 4
    mardroeme_setup_value: int = 8
    medic_revive_spy_draw_bonus: int = 5
    medic_revive_medic_bonus: int = 4


@dataclass(frozen=True, slots=True)
class LeaderPolicyTuningConfig:
    """Leader policy multipliers layered over profile weights."""

    immediate_need_gap_multiplier: float = 0.5
    elimination_round_pressure_multiplier: float = 0.5


@dataclass(frozen=True, slots=True)
class GreedyActionPolicyConfig:
    """Hand-tuned scores used by the simple greedy fallback bot."""

    leader_action_score: int = 12
    pass_score: int = -10
    unsupported_action_score: int = -100
    hero_unit_bonus: int = 15
    spy_unit_bonus: int = 10
    medic_unit_bonus: int = 8
    morale_boost_unit_bonus: int = 4
    tight_bond_unit_bonus: int = 4
    unit_horn_bonus: int = 6
    unit_scorch_row_bonus: int = 5
    scorch_special_bonus: int = 7
    clear_weather_special_bonus: int = 5
    decoy_special_bonus: int = 4
    horn_special_bonus: int = 6
    mardroeme_special_bonus: int = 4
    fallback_special_bonus: int = 3
    selection_hero_bonus: int = 10
    selection_medic_bonus: int = 6
    selection_spy_bonus: int = 4

    @property
    def special_card_bonuses(self) -> tuple[tuple[AbilityKind, int], ...]:
        return (
            (AbilityKind.SCORCH, self.scorch_special_bonus),
            (AbilityKind.CLEAR_WEATHER, self.clear_weather_special_bonus),
            (AbilityKind.DECOY, self.decoy_special_bonus),
            (AbilityKind.COMMANDERS_HORN, self.horn_special_bonus),
            (AbilityKind.MARDROEME, self.mardroeme_special_bonus),
        )


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Public-information search constants and leaf-evaluation scales.

    Search uses these numbers to bound candidate expansion, infer hidden
    opponent reply pressure, value terminal states, and discourage premature
    elimination-round passes while plausible continuation lines remain.
    """

    max_candidate_actions: int = 12
    max_opponent_replies: int = 3
    reply_search_score_gap_threshold: int = 12
    reply_search_min_hand_count: int = 1
    hidden_reply_unused_leader_bonus: float = 4.0
    hidden_reply_hand_parity_bonus: float = 2.0
    hidden_pending_choice_bonus: float = 2.0
    terminal_match_value: float = 100_000.0
    round_win_value: float = 1_000.0
    score_gap_scale: float = 1.0
    card_advantage_scale: float = 1.0
    hand_value_scale: float = 1.0
    leader_delta_scale: float = 1.0
    exact_finish_bonus_scale: float = 1.0
    draw_followup_scale: float = 1.0
    elimination_pass_live_line_margin: float = 10.0
    elimination_pass_live_line_penalty: float = 12.0
    optimistic_known_draw_floor: float = 4.0
    optimistic_known_draw_top_count: int = 3


@dataclass(frozen=True, slots=True)
class AIHandTunedPolicy:
    """Root policy object for every hand-tuned AI number in the engine package."""

    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    mulligan: MulliganPolicyConfig = field(default_factory=MulliganPolicyConfig)
    pending_choice: PendingChoicePolicyConfig = field(default_factory=PendingChoicePolicyConfig)
    evaluation: EvaluationPolicyConfig = field(default_factory=EvaluationPolicyConfig)
    tactical_values: TacticalValuePolicyConfig = field(default_factory=TacticalValuePolicyConfig)
    features: FeaturePolicyConfig = field(default_factory=FeaturePolicyConfig)
    projection: ProjectionPolicyConfig = field(default_factory=ProjectionPolicyConfig)
    leader_policy: LeaderPolicyTuningConfig = field(default_factory=LeaderPolicyTuningConfig)
    greedy: GreedyActionPolicyConfig = field(default_factory=GreedyActionPolicyConfig)
    search: SearchConfig = field(default_factory=SearchConfig)


DEFAULT_AI_POLICY = AIHandTunedPolicy()
DEFAULT_BASELINE_CONFIG = DEFAULT_AI_POLICY.baseline
DEFAULT_MULLIGAN_POLICY = DEFAULT_AI_POLICY.mulligan
DEFAULT_PENDING_CHOICE_POLICY = DEFAULT_AI_POLICY.pending_choice
DEFAULT_EVALUATION_POLICY = DEFAULT_AI_POLICY.evaluation
DEFAULT_TACTICAL_VALUE_POLICY = DEFAULT_AI_POLICY.tactical_values
DEFAULT_FEATURE_POLICY = DEFAULT_AI_POLICY.features
DEFAULT_PROJECTION_POLICY = DEFAULT_AI_POLICY.projection
DEFAULT_LEADER_POLICY_TUNING = DEFAULT_AI_POLICY.leader_policy
DEFAULT_GREEDY_ACTION_POLICY = DEFAULT_AI_POLICY.greedy
DEFAULT_SEARCH_CONFIG = DEFAULT_AI_POLICY.search

__all__ = [
    "AGGRESSIVE_LEADER_POLICY_ID",
    "CONSERVATIVE_LEADER_POLICY_ID",
    "DEFAULT_AI_POLICY",
    "DEFAULT_BASELINE_CONFIG",
    "DEFAULT_EVALUATION_POLICY",
    "DEFAULT_FEATURE_POLICY",
    "DEFAULT_GREEDY_ACTION_POLICY",
    "DEFAULT_LEADER_POLICY_TUNING",
    "DEFAULT_MULLIGAN_POLICY",
    "DEFAULT_PENDING_CHOICE_POLICY",
    "DEFAULT_PROJECTION_POLICY",
    "DEFAULT_SEARCH_CONFIG",
    "DEFAULT_TACTICAL_VALUE_POLICY",
    "LEGACY_PRESERVE_LEADER_POLICY_ID",
    "LEGACY_TEMPO_LEADER_POLICY_ID",
    "OPPORTUNISTIC_SCORCH_POLICY_ID",
    "RESERVE_SCORCH_POLICY_ID",
    "AIHandTunedPolicy",
    "ActionBonusConfig",
    "BaselineConfig",
    "CandidateConfig",
    "CandidateScoringConfig",
    "EvaluationPolicyConfig",
    "EvaluationWeights",
    "FeaturePolicyConfig",
    "GreedyActionPolicyConfig",
    "LeaderPolicyTuningConfig",
    "MulliganPolicyConfig",
    "MulliganScoreWeights",
    "PassConfig",
    "PendingChoicePolicyConfig",
    "PolicyResourceBias",
    "PolicySelection",
    "ProfileTuningConfig",
    "ProjectionPolicyConfig",
    "SearchConfig",
    "TacticalValuePolicyConfig",
]
