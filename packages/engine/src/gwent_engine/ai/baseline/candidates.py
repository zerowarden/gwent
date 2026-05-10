from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.ai.actions import action_to_id
from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.pending_choice import pending_choice_score
from gwent_engine.ai.baseline.projection import LeaderActionProjection, project_leader_action
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import BaselineConfig, CandidateScoringConfig
from gwent_engine.ai.utils import viewer_hand_definition
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType
from gwent_engine.core.actions import (
    GameAction,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.row_effects import special_ability_kind


@dataclass(frozen=True, slots=True)
class CandidateAction:
    action: GameAction
    coarse_score: float
    reason: str
    always_keep: bool = False


@dataclass(frozen=True, slots=True)
class CandidatePool:
    all_candidates: tuple[CandidateAction, ...]
    retained_candidates: tuple[CandidateAction, ...]


@dataclass(frozen=True, slots=True)
class _CandidateContext:
    observation: PlayerObservation
    card_registry: CardRegistry
    leader_registry: LeaderRegistry | None
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None

    def leader_projection(self, action: UseLeaderAbilityAction) -> LeaderActionProjection | None:
        return project_leader_action(
            action,
            observation=self.observation,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )

    def hand_definition(self, card_instance_id: CardInstanceId) -> CardDefinition | None:
        return viewer_hand_definition(
            card_instance_id,
            observation=self.observation,
            card_registry=self.card_registry,
            viewer_hand_definitions=self.viewer_hand_definitions,
        )

    def pending_choice_score(self, action: ResolveChoiceAction) -> int:
        return pending_choice_score(
            action,
            observation=self.observation,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )


def build_candidate_pool(
    observation: PlayerObservation,
    legal_actions: tuple[GameAction, ...],
    assessment: DecisionAssessment,
    *,
    config: BaselineConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> CandidatePool:
    context = _CandidateContext(
        observation=observation,
        card_registry=card_registry,
        leader_registry=leader_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    scored_candidates = tuple(
        sorted(
            (
                CandidateAction(
                    action=action,
                    coarse_score=_coarse_action_score(
                        action,
                        context,
                        config.candidate_scoring,
                    ),
                    reason=_candidate_reason(action, context),
                    always_keep=_always_keep(action, config=config, context=context),
                )
                for action in legal_actions
            ),
            key=lambda candidate: _candidate_sort_key(candidate),
        )
    )
    always_keep = [candidate for candidate in scored_candidates if candidate.always_keep]
    ranked = [candidate for candidate in scored_candidates if not candidate.always_keep]
    retained = always_keep + ranked[: max(0, assessment.legal_action_count)]
    deduped: dict[str, CandidateAction] = {}
    for candidate in retained:
        _ = deduped.setdefault(action_to_id(candidate.action), candidate)
    trimmed = tuple(
        sorted(
            deduped.values(),
            key=lambda candidate: _candidate_sort_key(candidate),
        )[: config.candidates.max_candidates]
    )
    return CandidatePool(
        all_candidates=scored_candidates,
        retained_candidates=trimmed,
    )


def build_candidates(
    observation: PlayerObservation,
    legal_actions: tuple[GameAction, ...],
    assessment: DecisionAssessment,
    *,
    config: BaselineConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> tuple[CandidateAction, ...]:
    return build_candidate_pool(
        observation,
        legal_actions,
        assessment,
        config=config,
        card_registry=card_registry,
        leader_registry=leader_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    ).retained_candidates


def shortlist_actions(
    candidates: tuple[CandidateAction, ...],
    *,
    candidate_limit: int,
) -> tuple[GameAction, ...]:
    if not candidates:
        return ()
    always_keep = [candidate for candidate in candidates if candidate.always_keep]
    ranked = sorted(
        (candidate for candidate in candidates if not candidate.always_keep),
        key=lambda candidate: (-candidate.coarse_score, action_to_id(candidate.action)),
    )
    retained = always_keep + ranked[: max(0, candidate_limit - len(always_keep))]
    deduped: dict[str, GameAction] = {}
    for candidate in retained:
        _ = deduped.setdefault(action_to_id(candidate.action), candidate.action)
    return tuple(sorted(deduped.values(), key=action_to_id))


def _coarse_action_score(
    action: GameAction,
    context: _CandidateContext,
    scoring: CandidateScoringConfig,
) -> float:
    match action:
        case PassAction():
            return scoring.pass_score
        case UseLeaderAbilityAction() as leader_action:
            return _leader_coarse_score(
                context.leader_projection(leader_action),
                scoring,
            )
        case ResolveChoiceAction() as resolve_choice_action:
            return float(context.pending_choice_score(resolve_choice_action))
        case PlayCardAction(card_instance_id=card_instance_id):
            return _play_card_coarse_score(context.hand_definition(card_instance_id), scoring)
        case _:
            return 0.0


def _leader_coarse_score(
    projection: LeaderActionProjection | None,
    scoring: CandidateScoringConfig,
) -> float:
    if projection is None:
        return scoring.unknown_leader_score
    if not projection.has_effect:
        return scoring.no_effect_leader_score
    return float(
        projection.projected_net_board_swing
        + projection.projected_hand_value_delta
        + (projection.viewer_hand_count_delta * scoring.leader_hand_delta_multiplier)
    )


def _play_card_coarse_score(
    definition: CardDefinition | None,
    scoring: CandidateScoringConfig,
) -> float:
    if definition is None:
        return 0.0
    if definition.card_type == CardType.UNIT:
        return float(definition.base_strength)
    return (
        scoring.high_value_special_score
        if _is_high_value_special(definition)
        else scoring.ordinary_special_score
    )


def _candidate_reason(
    action: GameAction,
    context: _CandidateContext,
) -> str:
    match action:
        case PassAction():
            return "pass option"
        case UseLeaderAbilityAction() as leader_action:
            return _leader_candidate_reason(context.leader_projection(leader_action))
        case ResolveChoiceAction():
            return "pending choice"
        case PlayCardAction(card_instance_id=card_instance_id):
            return _play_card_candidate_reason(context.hand_definition(card_instance_id))
        case _:
            return "action"


def _leader_candidate_reason(projection: LeaderActionProjection | None) -> str:
    if projection is None or projection.has_effect:
        return "leader ability"
    return "leader no-op"


def _play_card_candidate_reason(definition: CardDefinition | None) -> str:
    if definition is None:
        return "play card"
    if definition.card_type == CardType.UNIT:
        return "unit tempo"
    return _special_candidate_reason(special_ability_kind(definition))


def _special_candidate_reason(ability_kind: AbilityKind) -> str:
    match ability_kind:
        case AbilityKind.SCORCH:
            return "scorch special"
        case AbilityKind.DECOY:
            return "decoy special"
        case AbilityKind.CLEAR_WEATHER:
            return "clear weather special"
        case AbilityKind.COMMANDERS_HORN:
            return "horn special"
        case _:
            return "special card"


def _always_keep(
    action: GameAction,
    *,
    config: BaselineConfig,
    context: _CandidateContext,
) -> bool:
    if isinstance(action, PassAction):
        return config.candidates.always_keep_pass
    if isinstance(action, UseLeaderAbilityAction):
        return _always_keep_leader(action, config=config, context=context)
    if isinstance(action, PlayCardAction):
        return _always_keep_play_card(action, config=config, context=context)
    return False


def _always_keep_leader(
    action: UseLeaderAbilityAction,
    *,
    config: BaselineConfig,
    context: _CandidateContext,
) -> bool:
    if not config.candidates.always_keep_leader:
        return False
    projection = context.leader_projection(action)
    return projection is None or projection.has_effect


def _always_keep_play_card(
    action: PlayCardAction,
    *,
    config: BaselineConfig,
    context: _CandidateContext,
) -> bool:
    if not config.candidates.always_keep_tactical_specials:
        return False
    definition = context.hand_definition(action.card_instance_id)
    return (
        definition is not None
        and definition.card_type == CardType.SPECIAL
        and _is_tactical_special(definition)
    )


def _is_high_value_special(definition: CardDefinition) -> bool:
    return special_ability_kind(definition) in {
        AbilityKind.SCORCH,
        AbilityKind.DECOY,
        AbilityKind.CLEAR_WEATHER,
    }


def _is_tactical_special(definition: CardDefinition) -> bool:
    return special_ability_kind(definition) in {
        AbilityKind.SCORCH,
        AbilityKind.DECOY,
        AbilityKind.CLEAR_WEATHER,
        AbilityKind.COMMANDERS_HORN,
    }


def _candidate_sort_key(candidate: CandidateAction) -> tuple[int, float, str]:
    return (
        0 if candidate.always_keep else 1,
        -candidate.coarse_score,
        action_to_id(candidate.action),
    )
