from __future__ import annotations

from dataclasses import dataclass, field
from typing import override

from gwent_engine.ai.action_ids import action_to_id, mulligan_selection_id
from gwent_engine.ai.arena import MatchDecision, MatchTransition, MulliganDecision
from gwent_engine.ai.arena.models import FailedDecisionAttempt
from gwent_engine.ai.hashing import event_fingerprint

from gwent_evaluation.models import DecisionSample, MatchEvidence, TrajectoryStep
from gwent_evaluation.provenance import canonical_digest


@dataclass(slots=True)
class SummaryRecorder:
    """Constant-space action/event digest and timings; no retained observations or states."""

    decision_seconds: float = 0.0
    trace_digest: str = ""

    def record_decision(self, decision: MatchDecision) -> None:
        self.decision_seconds += decision.duration_seconds
        self.trace_digest = canonical_digest((self.trace_digest, _decision_identity(decision)))

    def record_transition(self, transition: MatchTransition) -> None:
        self.trace_digest = canonical_digest(
            (
                self.trace_digest,
                action_to_id(transition.action),
                tuple(event_fingerprint(event) for event in transition.events),
            )
        )

    def evidence(self) -> MatchEvidence:
        return MatchEvidence(samples=(), trajectory=(), trace_digest=self.trace_digest)


@dataclass(slots=True)
class ExperimentRecorder(SummaryRecorder):
    """Builds experiment evidence from the engine's behaviour-neutral hooks.

    Decision samples are player-safe; the trajectory retains privileged
    snapshots for replay and diagnosis and is never a training input.
    """

    samples: list[DecisionSample] = field(default_factory=list)
    trajectory: list[TrajectoryStep] = field(default_factory=list)

    @override
    def record_decision(self, decision: MatchDecision) -> None:
        SummaryRecorder.record_decision(self, decision)
        self.samples.append(
            DecisionSample(
                failure=decision.failure if isinstance(decision, FailedDecisionAttempt) else None,
                index=len(self.samples) + 1,
                kind=decision.kind,
                actor=decision.actor,
                observation=decision.observation,
                legal_option_ids=_legal_option_ids(decision),
                chosen_option_id=_chosen_option_id(decision),
                duration_seconds=decision.duration_seconds,
            )
        )

    @override
    def record_transition(self, transition: MatchTransition) -> None:
        SummaryRecorder.record_transition(self, transition)
        self.trajectory.append(
            TrajectoryStep(
                index=len(self.trajectory) + 1,
                kind=transition.kind,
                action_id=action_to_id(transition.action),
                state_before=transition.state_before,
                state_after=transition.state_after,
                event_fingerprints=tuple(event_fingerprint(event) for event in transition.events),
            )
        )

    @override
    def evidence(self) -> MatchEvidence:
        return MatchEvidence(
            trace_digest=self.trace_digest,
            samples=tuple(self.samples),
            trajectory=tuple(self.trajectory),
        )


def _decision_identity(decision: MatchDecision) -> object:
    if isinstance(decision, FailedDecisionAttempt):
        return (
            "failed_decision",
            decision.kind.value,
            decision.actor,
            decision.failure.stage.value,
            decision.failure.exception_type,
            decision.chosen_option_id,
        )
    return _chosen_option_id(decision)


def _legal_option_ids(decision: MatchDecision) -> tuple[str, ...]:
    if isinstance(decision, FailedDecisionAttempt):
        return decision.legal_option_ids
    if isinstance(decision, MulliganDecision):
        return tuple(mulligan_selection_id(selection) for selection in decision.legal_selections)
    return tuple(action_to_id(action) for action in decision.legal_actions)


def _chosen_option_id(decision: MatchDecision) -> str | None:
    if isinstance(decision, FailedDecisionAttempt):
        return decision.chosen_option_id
    if isinstance(decision, MulliganDecision):
        return mulligan_selection_id(decision.selection)
    return action_to_id(decision.action)
