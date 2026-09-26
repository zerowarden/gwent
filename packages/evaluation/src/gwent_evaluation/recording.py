from __future__ import annotations

from dataclasses import dataclass, field

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.arena import MatchDecision, MatchTransition, MulliganDecision
from gwent_engine.ai.hashing import event_fingerprint
from gwent_engine.core.actions import MulliganSelection

from gwent_evaluation.models import DecisionSample, MatchEvidence, TrajectoryStep


@dataclass(slots=True)
class ExperimentRecorder:
    """Builds experiment evidence from the engine's behaviour-neutral hooks.

    Decision samples are player-safe; the trajectory retains privileged
    snapshots for replay and diagnosis and is never a training input.
    """

    samples: list[DecisionSample] = field(default_factory=list)
    trajectory: list[TrajectoryStep] = field(default_factory=list)

    def record_decision(self, decision: MatchDecision) -> None:
        self.samples.append(
            DecisionSample(
                index=len(self.samples) + 1,
                kind=decision.kind,
                actor=decision.actor,
                observation=decision.observation,
                legal_option_ids=_legal_option_ids(decision),
                chosen_option_id=_chosen_option_id(decision),
                duration_seconds=decision.duration_seconds,
            )
        )

    def record_transition(self, transition: MatchTransition) -> None:
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

    def evidence(self) -> MatchEvidence:
        return MatchEvidence(
            samples=tuple(self.samples),
            trajectory=tuple(self.trajectory),
        )


def _legal_option_ids(decision: MatchDecision) -> tuple[str, ...]:
    if isinstance(decision, MulliganDecision):
        return tuple(_mulligan_selection_id(selection) for selection in decision.legal_selections)
    return tuple(action_to_id(action) for action in decision.legal_actions)


def _chosen_option_id(decision: MatchDecision) -> str:
    if isinstance(decision, MulliganDecision):
        return _mulligan_selection_id(decision.selection)
    return action_to_id(decision.action)


def _mulligan_selection_id(selection: MulliganSelection) -> str:
    cards = ",".join(str(card_id) for card_id in selection.cards_to_replace)
    return f"{selection.player_id}:{cards}"
