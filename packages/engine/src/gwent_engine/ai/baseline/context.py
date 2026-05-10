from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gwent_engine.ai.baseline.assessment import DecisionAssessment


class TempoState(StrEnum):
    AHEAD = "ahead"
    EVEN = "even"
    BEHIND = "behind"


class PressureMode(StrEnum):
    OPENING = "opening"
    CONTEST = "contest"
    OPPONENT_PASSED = "opponent_passed"
    ELIMINATION = "elimination"


class TacticalMode(StrEnum):
    PROBE = "probe"
    CONTEST = "contest"
    PROTECT_LEAD = "protect_lead"
    FINISH_AFTER_PASS = "finish_after_pass"
    ALL_IN = "all_in"


@dataclass(frozen=True, slots=True)
class DecisionContext:
    tempo: TempoState
    mode: TacticalMode
    preserve_resources: bool

    @property
    def pressure(self) -> PressureMode:
        return {
            TacticalMode.PROBE: PressureMode.OPENING,
            TacticalMode.CONTEST: PressureMode.CONTEST,
            TacticalMode.PROTECT_LEAD: PressureMode.CONTEST,
            TacticalMode.FINISH_AFTER_PASS: PressureMode.OPPONENT_PASSED,
            TacticalMode.ALL_IN: PressureMode.ELIMINATION,
        }[self.mode]

    @property
    def prioritize_card_advantage(self) -> bool:
        return self.mode in {
            TacticalMode.PROBE,
            TacticalMode.CONTEST,
            TacticalMode.PROTECT_LEAD,
        }

    @property
    def prioritize_immediate_points(self) -> bool:
        return self.mode in {
            TacticalMode.FINISH_AFTER_PASS,
            TacticalMode.ALL_IN,
        }

    @property
    def minimum_commitment_mode(self) -> bool:
        return self.mode == TacticalMode.FINISH_AFTER_PASS


def classify_context(assessment: DecisionAssessment) -> DecisionContext:
    if assessment.score_gap > 0:
        tempo = TempoState.AHEAD
    elif assessment.score_gap < 0:
        tempo = TempoState.BEHIND
    else:
        tempo = TempoState.EVEN

    preserve_resources = not assessment.is_elimination_round and (
        assessment.card_advantage >= 0
        or assessment.round_number == 1
        or assessment.opponent.hand_count >= assessment.viewer.hand_count
    )
    if assessment.opponent_passed:
        mode = TacticalMode.FINISH_AFTER_PASS
    elif assessment.is_elimination_round:
        mode = TacticalMode.ALL_IN
    elif tempo == TempoState.AHEAD and preserve_resources:
        mode = TacticalMode.PROTECT_LEAD
    elif assessment.viewer.board_strength == 0 and assessment.opponent.board_strength == 0:
        mode = TacticalMode.PROBE
    else:
        mode = TacticalMode.CONTEST
    return DecisionContext(
        tempo=tempo,
        mode=mode,
        preserve_resources=preserve_resources,
    )
