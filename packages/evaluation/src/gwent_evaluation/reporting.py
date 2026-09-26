"""Assemble reproducible run reports and reference/candidate comparisons.

`load_run` reads the immutable inputs and persisted results of one run without
executing any game. `build_run_report` turns those records into descriptive
scores, strata, and block-level uncertainty. `build_run_comparison` pairs two
compatible runs by balanced block and reports the candidate-minus-reference
difference, refusing to present an inferential interval when either run is
incomplete or the runs are not structurally comparable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import fsum
from pathlib import Path

from gwent_engine.ai.arena import TerminationReason

from gwent_evaluation.metrics import (
    DEFAULT_BOOTSTRAP,
    BlockDifference,
    BootstrapConfig,
    CaseStatus,
    RunMetrics,
    ScoredCase,
    ScoreInterval,
    ScoreSummary,
    StratumMetrics,
    compare_block_scores,
    compute_run_metrics,
    insufficient_sample_interval,
)
from gwent_evaluation.models import (
    RECORD_SCHEMA_VERSION,
    MatchResult,
    RunManifest,
    ScheduledMatch,
)
from gwent_evaluation.records import CorruptRecordError, record_to_dict
from gwent_evaluation.schedule import ScheduleBlock, schedule_blocks
from gwent_evaluation.storage import RunStore


class ReportError(ValueError):
    """Raised when persisted records cannot be turned into a coherent report."""


@dataclass(frozen=True, slots=True)
class LatencySummary:
    decisions: int
    transitions: int
    decision_seconds: float
    execution_seconds: float
    mean_decision_seconds: float | None
    transitions_per_second: float | None


@dataclass(frozen=True, slots=True)
class RunReport:
    """Scores, uncertainty, coverage, and validity of one persisted run."""

    schema_version: int
    run_id: str
    suite_id: str
    purpose: str
    observation_contract_version: int
    planned_matches: int
    executed_matches: int
    completed_matches: int
    failed_matches: int
    missing_matches: int
    candidate: ScoreSummary
    balanced_score: float | None
    complete_blocks: int
    total_blocks: int
    interval: ScoreInterval
    strata: tuple[StratumMetrics, ...]
    latency: LatencySummary
    valid_for_comparison: bool
    validity_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedRun:
    """One run's immutable inputs and any results persisted so far."""

    manifest: RunManifest
    matches: tuple[ScheduledMatch, ...]
    results: Mapping[str, MatchResult]


@dataclass(frozen=True, slots=True)
class RunComparison:
    """Candidate-minus-reference comparison over paired complete blocks."""

    compatible: bool
    valid: bool
    reasons: tuple[str, ...]
    reference_run_id: str
    candidate_run_id: str
    reference_agent_id: str
    candidate_agent_id: str
    reference_score: float | None
    candidate_score: float | None
    mean_difference: float | None
    interval: ScoreInterval
    block_differences: tuple[BlockDifference, ...]


def load_run(run_root: Path) -> LoadedRun:
    store = RunStore.from_root(run_root)
    manifest = store.read_manifest()
    matches = store.read_schedule()
    _verify_schedule_identity(manifest, matches)
    results: dict[str, MatchResult] = {}
    for match in matches:
        result = store.read_result(match.case_id)
        if result is not None:
            results[match.case_id] = result
    return LoadedRun(manifest=manifest, matches=matches, results=results)


def build_run_report(
    loaded: LoadedRun,
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> RunReport:
    blocks = schedule_blocks(loaded.manifest.suite)
    metrics = compute_run_metrics(
        scored_cases(blocks, loaded.results),
        bootstrap=bootstrap,
    )
    suite = loaded.manifest.suite
    return RunReport(
        schema_version=RECORD_SCHEMA_VERSION,
        run_id=loaded.manifest.run_id,
        suite_id=suite.suite_id,
        purpose=suite.purpose.value,
        observation_contract_version=suite.observation_contract_version,
        planned_matches=metrics.planned,
        executed_matches=metrics.executed,
        completed_matches=metrics.completed,
        failed_matches=metrics.failed,
        missing_matches=metrics.missing,
        candidate=metrics.candidate,
        balanced_score=metrics.balanced_score,
        complete_blocks=metrics.complete_blocks,
        total_blocks=metrics.total_blocks,
        interval=metrics.interval,
        strata=metrics.strata,
        latency=_latency_summary(loaded.results.values()),
        valid_for_comparison=metrics.valid,
        validity_reasons=metrics.validity_reasons,
    )


def persist_run_report(
    store: RunStore,
    loaded: LoadedRun,
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> RunReport:
    report = build_run_report(loaded, bootstrap=bootstrap)
    store.write_report(record_to_dict(report), render_report_markdown(report))
    return report


def report_run(
    run_root: Path,
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> RunReport:
    """Rebuild and persist the report of an existing run directory."""

    store = RunStore.from_root(run_root)
    return persist_run_report(store, load_run(run_root), bootstrap=bootstrap)


def build_run_comparison(
    reference: LoadedRun,
    candidate: LoadedRun,
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> RunComparison:
    structural_reasons = _compatibility_reasons(reference, candidate)
    if structural_reasons:
        return _diagnostic_comparison(reference, candidate, structural_reasons, bootstrap=bootstrap)
    reference_cases = scored_cases(
        schedule_blocks(reference.manifest.suite),
        reference.results,
    )
    candidate_cases = scored_cases(
        schedule_blocks(candidate.manifest.suite),
        candidate.results,
    )
    reasons = (
        *_run_validity_reasons(
            "reference", compute_run_metrics(reference_cases, bootstrap=bootstrap)
        ),
        *_run_validity_reasons(
            "candidate", compute_run_metrics(candidate_cases, bootstrap=bootstrap)
        ),
    )
    valid = not reasons
    paired = compare_block_scores(reference_cases, candidate_cases, bootstrap=bootstrap)
    return RunComparison(
        compatible=True,
        valid=valid,
        reasons=reasons,
        reference_run_id=reference.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        reference_agent_id=reference.manifest.candidate.agent_id,
        candidate_agent_id=candidate.manifest.candidate.agent_id,
        reference_score=paired.reference_score,
        candidate_score=paired.candidate_score,
        mean_difference=paired.mean_difference,
        interval=(
            paired.interval
            if valid
            else insufficient_sample_interval(blocks=len(paired.blocks), config=bootstrap)
        ),
        block_differences=paired.blocks,
    )


def _diagnostic_comparison(
    reference: LoadedRun,
    candidate: LoadedRun,
    reasons: tuple[str, ...],
    *,
    bootstrap: BootstrapConfig,
) -> RunComparison:
    return RunComparison(
        compatible=False,
        valid=False,
        reasons=reasons,
        reference_run_id=reference.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        reference_agent_id=reference.manifest.candidate.agent_id,
        candidate_agent_id=candidate.manifest.candidate.agent_id,
        reference_score=None,
        candidate_score=None,
        mean_difference=None,
        interval=insufficient_sample_interval(blocks=0, config=bootstrap),
        block_differences=(),
    )


def compare_runs(
    reference_root: Path,
    candidate_root: Path,
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> RunComparison:
    return build_run_comparison(
        load_run(reference_root),
        load_run(candidate_root),
        bootstrap=bootstrap,
    )


def scored_cases(
    blocks: Sequence[ScheduleBlock],
    results: Mapping[str, MatchResult],
) -> tuple[ScoredCase, ...]:
    """Adapt scheduled legs and persisted results into pure scoring facts."""

    return tuple(
        _scored_case(block, match, results.get(match.case_id))
        for block in blocks
        for match in block.matches
    )


def render_report_markdown(report: RunReport) -> str:
    resamples = report.interval.resamples
    lines = [
        f"# Run report: {report.run_id}",
        "",
        f"- Suite: {report.suite_id} ({report.purpose})",
        f"- Observation contract: v{report.observation_contract_version}",
        "",
        "## Coverage",
        "",
        "| Planned | Executed | Completed | Failed | Missing | Valid |",
        "| --- | --- | --- | --- | --- | --- |",
        "| "
        + " | ".join(
            str(value)
            for value in (
                report.planned_matches,
                report.executed_matches,
                report.completed_matches,
                report.failed_matches,
                report.missing_matches,
                _yes_no(report.valid_for_comparison),
            )
        )
        + " |",
        "",
        "## Candidate score",
        "",
        "| Wins | Draws | Losses | Completed | Score | Balanced |",
        "| --- | --- | --- | --- | --- | --- |",
        "| "
        + " | ".join(
            (
                str(report.candidate.wins),
                str(report.candidate.draws),
                str(report.candidate.losses),
                str(report.candidate.completed),
                _format_float(report.candidate.score),
                _format_float(report.balanced_score),
            )
        )
        + " |",
        "",
        "## Uncertainty",
        "",
        f"- Method: `{report.interval.method.value}`",
        f"- Confidence: {report.interval.confidence_level:.2f}",
        f"- Interval: [{_format_float(report.interval.lower)}, "
        + f"{_format_float(report.interval.upper)}]",
        f"- Complete blocks: {report.complete_blocks} of {report.total_blocks}",
        f"- Resamples: {resamples if resamples is not None else 'n/a'}",
        "",
        "## Latency",
        "",
        "| "
        + " | ".join(
            (
                "Decisions",
                "Transitions",
                "Decision seconds",
                "Execution seconds",
                "Mean decision seconds",
                "Transitions/second",
            )
        )
        + " |",
        "| --- | --- | --- | --- | --- | --- |",
        "| "
        + " | ".join(
            (
                str(report.latency.decisions),
                str(report.latency.transitions),
                f"{report.latency.decision_seconds:.6f}",
                f"{report.latency.execution_seconds:.6f}",
                _format_float(report.latency.mean_decision_seconds, digits=6),
                _format_float(report.latency.transitions_per_second, digits=3),
            )
        )
        + " |",
        "",
        "## Strata",
        "",
        "| Dimension | Value | Wins | Draws | Losses | Completed | Score | Interval |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for stratum in report.strata:
        lines.append(
            "| "
            + " | ".join(
                (
                    stratum.dimension,
                    stratum.value,
                    str(stratum.summary.wins),
                    str(stratum.summary.draws),
                    str(stratum.summary.losses),
                    str(stratum.summary.completed),
                    _format_float(stratum.summary.score),
                    stratum.interval.method.value,
                )
            )
            + " |"
        )
    if report.validity_reasons:
        lines.extend(("", "## Validity", ""))
        lines.extend(f"- {reason}" for reason in report.validity_reasons)
    return "\n".join(lines) + "\n"


def render_comparison_markdown(comparison: RunComparison) -> str:
    lines = [
        f"# Run comparison: {comparison.reference_run_id} -> {comparison.candidate_run_id}",
        "",
        f"- Compatible: {_yes_no(comparison.compatible)}",
        f"- Valid for comparison: {_yes_no(comparison.valid)}",
        f"- Reference agent: {comparison.reference_agent_id}",
        f"- Candidate agent: {comparison.candidate_agent_id}",
        f"- Paired blocks: {len(comparison.block_differences)}",
        f"- Reference score: {_format_float(comparison.reference_score)}",
        f"- Candidate score: {_format_float(comparison.candidate_score)}",
        f"- Mean difference (candidate - reference): {_format_float(comparison.mean_difference)}",
        f"- Interval method: `{comparison.interval.method.value}`",
        f"- Interval: [{_format_float(comparison.interval.lower)}, "
        + f"{_format_float(comparison.interval.upper)}]",
    ]
    if comparison.reasons:
        lines.extend(("", "## Reasons", ""))
        lines.extend(f"- {reason}" for reason in comparison.reasons)
    if comparison.block_differences:
        lines.extend(
            (
                "",
                "## Paired blocks",
                "",
                "| Block | Reference | Candidate | Difference |",
                "| --- | --- | --- | --- |",
            )
        )
        for block in comparison.block_differences:
            lines.append(
                f"| {block.block_id} | {_format_float(block.reference_score)} | "
                + f"{_format_float(block.candidate_score)} | {_format_float(block.difference)} |"
            )
    return "\n".join(lines) + "\n"


def _scored_case(
    block: ScheduleBlock,
    match: ScheduledMatch,
    result: MatchResult | None,
) -> ScoredCase:
    status, score = _case_status(result)
    return ScoredCase(
        case_id=match.case_id,
        block_id=block.block_id,
        status=status,
        score=score,
        strata={
            "opponent": match.opponent_agent.agent_id,
            "candidate_seat": str(match.candidate_seat),
            "requested_starting_player": str(match.requested_starting_player),
            "candidate_deck": match.candidate_deck_id,
            "opponent_deck": match.opponent_deck_id,
        },
    )


def _case_status(result: MatchResult | None) -> tuple[CaseStatus, float | None]:
    if result is None:
        return CaseStatus.MISSING, None
    if result.termination is not TerminationReason.COMPLETED:
        return CaseStatus.FAILED, None
    if result.candidate_score is None:
        raise ReportError(f"Completed case {result.case_id!r} has no candidate score.")
    return CaseStatus.COMPLETED, result.candidate_score


def _latency_summary(results: Iterable[MatchResult]) -> LatencySummary:
    collected = tuple(results)
    decisions = sum(result.decision_count for result in collected)
    transitions = sum(result.accepted_transitions for result in collected)
    decision_seconds = fsum(result.decision_seconds for result in collected)
    execution_seconds = fsum(result.execution_seconds for result in collected)
    return LatencySummary(
        decisions=decisions,
        transitions=transitions,
        decision_seconds=decision_seconds,
        execution_seconds=execution_seconds,
        mean_decision_seconds=(decision_seconds / decisions if decisions else None),
        transitions_per_second=(transitions / execution_seconds if execution_seconds > 0 else None),
    )


def _verify_schedule_identity(
    manifest: RunManifest,
    matches: Sequence[ScheduledMatch],
) -> None:
    expected = {
        match.case_id: match for block in schedule_blocks(manifest.suite) for match in block.matches
    }
    scheduled = tuple(match.case_id for match in matches)
    if len(set(scheduled)) != len(scheduled):
        raise CorruptRecordError("The persisted schedule contains duplicate case ids.")
    if set(scheduled) != set(manifest.planned_case_ids):
        raise CorruptRecordError(
            f"The persisted schedule of run {manifest.run_id!r} does not match its manifest."
        )
    for match in matches:
        if expected.get(match.case_id) != match:
            raise CorruptRecordError(
                f"Scheduled match {match.case_id!r} does not match its manifest."
            )


def _compatibility_reasons(reference: LoadedRun, candidate: LoadedRun) -> tuple[str, ...]:
    reference_manifest = reference.manifest
    candidate_manifest = candidate.manifest
    reasons: list[str] = []
    if reference_manifest.suite.suite_id != candidate_manifest.suite.suite_id:
        reasons.append(
            f"suite ids differ: {reference_manifest.suite.suite_id!r} vs "
            + f"{candidate_manifest.suite.suite_id!r}"
        )
    if set(reference_manifest.planned_case_ids) != set(candidate_manifest.planned_case_ids):
        reasons.append("scheduled case sets differ")
    contracts = (
        reference_manifest.suite.observation_contract_version,
        candidate_manifest.suite.observation_contract_version,
    )
    if contracts[0] != contracts[1]:
        reasons.append(f"observation contract versions differ: {contracts[0]} vs {contracts[1]}")
    versions = (
        reference_manifest.seed_derivation_version,
        candidate_manifest.seed_derivation_version,
    )
    if versions[0] != versions[1]:
        reasons.append(f"seed derivation versions differ: {versions[0]} vs {versions[1]}")
    case_versions = (reference_manifest.case_id_version, candidate_manifest.case_id_version)
    if case_versions[0] != case_versions[1]:
        reasons.append(f"case id versions differ: {case_versions[0]} vs {case_versions[1]}")
    if reference_manifest.assets != candidate_manifest.assets:
        reasons.append("asset identities differ")
    commits = (reference_manifest.repository.commit, candidate_manifest.repository.commit)
    if commits[0] != commits[1]:
        reasons.append(f"repository commits differ: {commits[0]} vs {commits[1]}")
    lockfiles = (
        reference_manifest.repository.lockfile_digest,
        candidate_manifest.repository.lockfile_digest,
    )
    if lockfiles[0] != lockfiles[1]:
        reasons.append("lockfile digests differ")
    if reference_manifest.runtime != candidate_manifest.runtime:
        reasons.append("runtime identities differ")
    return tuple(reasons)


def _run_validity_reasons(label: str, metrics: RunMetrics) -> tuple[str, ...]:
    return tuple(f"{label} run: {reason}" for reason in metrics.validity_reasons)


def _format_float(value: float | None, *, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


__all__ = [
    "LatencySummary",
    "LoadedRun",
    "ReportError",
    "RunComparison",
    "RunReport",
    "build_run_comparison",
    "build_run_report",
    "compare_runs",
    "load_run",
    "persist_run_report",
    "render_comparison_markdown",
    "render_report_markdown",
    "report_run",
    "scored_cases",
]
