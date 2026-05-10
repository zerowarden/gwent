from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import cast

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext, TacticalMode
from gwent_engine.ai.baseline.policies import (
    LeaderPolicy,
    ScorchPolicy,
)
from gwent_engine.ai.baseline.policies.registry import (
    POLICY_CATALOG,
    PolicyBundle,
)
from gwent_engine.ai.baseline.profile_catalog import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    ProfilePassOverrides,
    ProfileWeightOverrides,
)
from gwent_engine.ai.policy import (
    ActionBonusConfig,
    BaselineConfig,
    EvaluationWeights,
    PassConfig,
    PolicyResourceBias,
    PolicySelection,
    ProfileTuningConfig,
)


@dataclass(frozen=True, slots=True)
class WeightAdjustment:
    label: str
    factor: float


@dataclass(frozen=True, slots=True)
class WeightProvenance:
    name: str
    base_config: float
    profile_override: float | None
    adjustments: tuple[WeightAdjustment, ...]
    resolved: float


@dataclass(frozen=True, slots=True)
class HeuristicProfile:
    profile_id: str
    policy_names: PolicySelection
    weights: EvaluationWeights
    weight_provenance: tuple[WeightProvenance, ...]
    action_bonus: ActionBonusConfig
    candidate_limit: int
    pass_lead_margin: int
    estimated_opponent_tempo_per_card: int
    elimination_estimated_opponent_tempo_per_card: int
    minimum_commitment_bias: float
    preserve_resources_bias: float
    scorch_policy: ScorchPolicy
    leader_policy: LeaderPolicy

    @property
    def resource_bias(self) -> PolicyResourceBias:
        return PolicyResourceBias(
            minimum_commitment=self.minimum_commitment_bias,
            preserve_resources=self.preserve_resources_bias,
        )

    @classmethod
    def from_components(
        cls,
        *,
        profile_id: str,
        policy_names: PolicySelection,
        resolved_policies: PolicyBundle,
        weights: EvaluationWeights,
        weight_provenance: tuple[WeightProvenance, ...],
        action_bonus: ActionBonusConfig,
        candidate_limit: int,
        pass_lead_margin: int,
        estimated_opponent_tempo_per_card: int,
        elimination_estimated_opponent_tempo_per_card: int,
        minimum_commitment_bias: float,
        preserve_resources_bias: float,
    ) -> HeuristicProfile:
        """Build a profile from resolved policy wiring and tuned values.

        This keeps `compose_profile` focused on policy selection while the
        dataclass constructor stays readable.
        """

        return cls(
            profile_id=profile_id,
            policy_names=policy_names,
            weights=weights,
            weight_provenance=weight_provenance,
            action_bonus=action_bonus,
            candidate_limit=candidate_limit,
            pass_lead_margin=pass_lead_margin,
            estimated_opponent_tempo_per_card=estimated_opponent_tempo_per_card,
            elimination_estimated_opponent_tempo_per_card=(
                elimination_estimated_opponent_tempo_per_card
            ),
            minimum_commitment_bias=minimum_commitment_bias,
            preserve_resources_bias=preserve_resources_bias,
            scorch_policy=resolved_policies.scorch,
            leader_policy=resolved_policies.leader,
        )


def compose_profile(
    config: BaselineConfig,
    assessment: DecisionAssessment,
    context: DecisionContext,
    *,
    base_profile: BaseProfileDefinition = DEFAULT_BASE_PROFILE,
) -> HeuristicProfile:
    tuning = config.profile_tuning
    weights, weight_provenance = _resolve_weights(
        config.weights,
        base_profile.weights,
        context=context,
        tuning=tuning,
    )
    pass_config = _apply_pass_overrides(
        config.pass_logic,
        base_profile.pass_overrides,
    )
    if assessment.pending_choice_source_kind is not None:
        candidate_limit = max(assessment.legal_action_count, 1)
    elif context.mode == TacticalMode.FINISH_AFTER_PASS:
        candidate_limit = min(
            config.candidates.max_candidates,
            tuning.opponent_passed_candidate_limit,
        )
    else:
        candidate_limit = config.candidates.max_candidates
    pass_lead_margin = (
        pass_config.elimination_safe_lead_margin
        if context.mode == TacticalMode.ALL_IN
        else pass_config.safe_lead_margin
    )
    policy_names = base_profile.policies
    return HeuristicProfile.from_components(
        profile_id=base_profile.profile_id,
        policy_names=policy_names,
        resolved_policies=POLICY_CATALOG.resolve(policy_names),
        weights=weights,
        weight_provenance=weight_provenance,
        action_bonus=config.action_bonus,
        candidate_limit=candidate_limit,
        pass_lead_margin=pass_lead_margin,
        estimated_opponent_tempo_per_card=pass_config.estimated_opponent_tempo_per_card,
        elimination_estimated_opponent_tempo_per_card=(
            pass_config.elimination_estimated_opponent_tempo_per_card
        ),
        minimum_commitment_bias=(
            tuning.minimum_commitment_mode_bias
            if context.minimum_commitment_mode
            else tuning.neutral_commitment_mode_bias
        ),
        preserve_resources_bias=(
            tuning.preserve_resources_bias
            if context.preserve_resources
            else tuning.spend_resources_bias
        ),
    )


def _resolve_weights(
    weights: EvaluationWeights,
    overrides: ProfileWeightOverrides,
    *,
    context: DecisionContext,
    tuning: ProfileTuningConfig,
) -> tuple[EvaluationWeights, tuple[WeightProvenance, ...]]:
    override_values: dict[str, float | None] = {
        field_name: value
        for field_name, value in {
            "immediate_points": overrides.immediate_points,
            "card_advantage": overrides.card_advantage,
            "remaining_hand_value": overrides.remaining_hand_value,
            "leader_value": overrides.leader_value,
            "overcommit_penalty": overrides.overcommit_penalty,
            "exact_finish_bonus": overrides.exact_finish_bonus,
        }.items()
    }
    resolved_updates: dict[str, float] = {}
    provenance: list[WeightProvenance] = []
    for field_info in fields(EvaluationWeights):
        name = field_info.name
        base_value = float(cast(float, getattr(weights, name)))
        profile_override = override_values.get(name)
        current_value = float(profile_override) if profile_override is not None else base_value
        adjustments: list[WeightAdjustment] = []
        if context.prioritize_card_advantage:
            match name:
                case "card_advantage" | "remaining_hand_value":
                    adjustments.append(
                        WeightAdjustment(
                            "economy_weight_multiplier",
                            tuning.economy_weight_multiplier,
                        )
                    )
                case "leader_value":
                    adjustments.append(
                        WeightAdjustment(
                            "leader_preservation_multiplier",
                            tuning.leader_preservation_multiplier,
                        )
                    )
                case _:
                    pass
        if context.prioritize_immediate_points:
            match name:
                case "immediate_points" | "exact_finish_bonus" | "overcommit_penalty":
                    adjustments.append(
                        WeightAdjustment(
                            "tempo_weight_multiplier",
                            tuning.tempo_weight_multiplier,
                        )
                    )
                case _:
                    pass
        if context.minimum_commitment_mode:
            match name:
                case "exact_finish_bonus" | "overcommit_penalty":
                    adjustments.append(
                        WeightAdjustment(
                            "minimum_commitment_weight_multiplier",
                            tuning.minimum_commitment_weight_multiplier,
                        )
                    )
                case _:
                    pass
        resolved_value = current_value
        for adjustment in adjustments:
            resolved_value *= adjustment.factor
        resolved_updates[name] = resolved_value
        provenance.append(
            WeightProvenance(
                name=name,
                base_config=base_value,
                profile_override=(None if profile_override is None else float(profile_override)),
                adjustments=tuple(adjustments),
                resolved=resolved_value,
            )
        )
    return replace(weights, **resolved_updates), tuple(provenance)


def _apply_pass_overrides(
    pass_config: PassConfig,
    overrides: ProfilePassOverrides,
) -> PassConfig:
    updates = {
        field_name: value
        for field_name, value in {
            "safe_lead_margin": overrides.safe_lead_margin,
            "elimination_safe_lead_margin": overrides.elimination_safe_lead_margin,
            "estimated_opponent_tempo_per_card": overrides.estimated_opponent_tempo_per_card,
            "elimination_estimated_opponent_tempo_per_card": (
                overrides.elimination_estimated_opponent_tempo_per_card
            ),
        }.items()
        if value is not None
    }
    return replace(pass_config, **updates) if updates else pass_config
