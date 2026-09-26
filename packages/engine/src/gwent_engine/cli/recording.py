from __future__ import annotations

from dataclasses import dataclass, field

from gwent_engine.ai.arena import MatchDecision, MatchTransition
from gwent_engine.cards import CardRegistry
from gwent_engine.cli.models import CliStep
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.scoring import battlefield_effective_strengths


@dataclass(slots=True)
class CliMatchRecorder:
    """Rich diagnostic recorder owned by the interactive review workflow.

    This is the only recorder that retains authoritative snapshots, strength
    maps, and round-summary states; bulk evaluation uses the evaluation
    package's experiment recorder instead.
    """

    card_registry: CardRegistry
    leader_registry: LeaderRegistry
    steps: list[CliStep] = field(default_factory=list)
    pending_choice_state: GameState | None = None

    def record_decision(self, decision: MatchDecision) -> None:
        del decision

    def record_transition(self, transition: MatchTransition) -> None:
        if self.pending_choice_state is None and transition.state_after.pending_choice is not None:
            self.pending_choice_state = transition.state_after
        round_summary_state = transition.round_summary_state
        self.steps.append(
            CliStep(
                transition=transition,
                effective_strengths_before=battlefield_effective_strengths(
                    transition.state_before,
                    card_registry=self.card_registry,
                    leader_registry=self.leader_registry,
                ),
                effective_strengths_after=battlefield_effective_strengths(
                    transition.state_after,
                    card_registry=self.card_registry,
                    leader_registry=self.leader_registry,
                ),
                round_summary_strengths=(
                    battlefield_effective_strengths(
                        round_summary_state,
                        card_registry=self.card_registry,
                        leader_registry=self.leader_registry,
                    )
                    if round_summary_state is not None
                    else {}
                ),
            )
        )
