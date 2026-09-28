"""Shared report data for Markdown, JSON, and HTML presentation."""

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_evaluation.records import record_to_dict

LIMITATIONS = (
    "Fixed decks and opponents; additional seeds do not establish unseen-deck strength.",
    "Fixed tactical structure, shortlist, overrides, and non-tunable configuration.",
    "Optimization and validation are selection-affected development evidence.",
    "Only explicit held-out confirmation can support promotion under the frozen thresholds.",
    "Decision latency is diagnostic, depends on machine/load, and never enters fitness.",
)


@dataclass(frozen=True, slots=True)
class StudyReport:
    study_id: str
    study_digest: str
    stage: str
    engineering: str
    measurement: str
    verdict: str
    reasons: tuple[str, ...]
    inputs: Mapping[str, object]
    sensitivity: Mapping[str, object] | None
    parameters: tuple[Mapping[str, object], ...]
    methods: tuple[Mapping[str, object], ...]
    runs: tuple[Mapping[str, object], ...]
    validation: Mapping[str, object] | None
    confirmation: Mapping[str, object] | None
    verification: Mapping[str, object] | None
    artifacts: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, **record_to_dict(self), "limitations": LIMITATIONS}
