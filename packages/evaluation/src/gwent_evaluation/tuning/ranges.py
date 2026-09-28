"""Frozen one-weight sweeps and independent development rechecks; never promotion."""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from gwent_shared.extract import expect_sequence

from gwent_evaluation.execution import candidate_manifest, validate_run_environment
from gwent_evaluation.html_report import table
from gwent_evaluation.models import RunManifest, SpecError
from gwent_evaluation.progress import TerminalProgress, advance, stage
from gwent_evaluation.provenance import default_repository_root
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.reporting import build_run_report
from gwent_evaluation.storage import RunConflictError, RunStore, read_record_mapping
from gwent_evaluation.tuning.models import StudyMode, StudySpec, SweepPoint
from gwent_evaluation.tuning.objective import RecordedEvaluation, evaluate_recorded_candidate
from gwent_evaluation.tuning.parameters import encode_parameters, finite_float
from gwent_evaluation.tuning.range_reports import (
    index_sections,
    write_benchmark,
    write_range_plan,
    write_report,
    write_stage_report,
)
from gwent_evaluation.tuning.selection import assess_candidate
from gwent_evaluation.tuning.sensitivity import require_sensitivity, run_sensitivity
from gwent_evaluation.tuning.specs import load_study_spec, study_from_dict
from gwent_evaluation.tuning.storage import StudyStore, read_checked_document


def sweep_points(study: StudySpec, multipliers: tuple[float, ...]) -> tuple[SweepPoint, ...]:
    original = encode_parameters(
        study.parameter_space, study.incumbent, frozen_configuration=study.incumbent
    )
    points: list[SweepPoint] = []
    for index, parameter in enumerate(study.parameter_space.parameters):
        default = cast(float, getattr(study.incumbent.baseline.weights, parameter.name))
        values = sorted(
            {max(parameter.lower, min(parameter.upper, default * m)) for m in multipliers}
        )
        for value in values:
            if value == default:
                continue
            coordinates = list(original)
            coordinates[index] = (value - parameter.lower) / (parameter.upper - parameter.lower)
            candidate = study.bind(tuple(coordinates))
            points.append(SweepPoint(parameter.name, value, tuple(coordinates), candidate.digest()))
    return tuple(points)


def load_protocol(path: Path, repository: Path) -> tuple[StudySpec, tuple[float, ...]]:
    raw = read_record_mapping(path)
    if (
        set(raw)
        != {
            "schema_version",
            "study_spec",
            "multipliers",
            "selection",
            "maximum_rechecks_per_parameter",
        }
        or type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
        or raw["selection"] != "best_positive_score_then_nearest_incumbent_then_digest"
        or type(raw["maximum_rechecks_per_parameter"]) is not int
        or raw["maximum_rechecks_per_parameter"] != 1
        or not isinstance(raw["study_spec"], str)
    ):
        raise SpecError("Unsupported range investigation protocol.")
    multipliers = tuple(
        finite_float(v, context="multiplier")
        for v in expect_sequence(raw["multipliers"], context="multipliers", error_factory=SpecError)
    )
    if (
        len(set(multipliers)) != len(multipliers)
        or len(multipliers) < 3
        or min(multipliers) < 0
        or 1 not in multipliers
    ):
        raise SpecError("Declare distinct nonnegative multipliers including the incumbent (1).")
    return load_study_spec(path.parent / raw["study_spec"], repository_root=repository), multipliers


def nominate_ranges(study: StudySpec, rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    chosen: list[str] = []
    for parameter in study.parameter_space.parameters:
        default = cast(float, getattr(study.incumbent.baseline.weights, parameter.name))
        eligible = [
            row
            for row in rows
            if row["parameter"] == parameter.name and cast(float, row["difference"]) > 0
        ]
        if eligible:
            best = min(
                eligible,
                key=lambda row: (
                    -cast(float, row["difference"]),
                    abs(cast(float, row["value"]) - default),
                    str(row["configuration_digest"]),
                ),
            )
            chosen.append(cast(str, best["configuration_digest"]))
    return tuple(chosen)


def summarize_point(
    study: StudySpec,
    point: SweepPoint,
    reference: RecordedEvaluation,
    evaluation: RecordedEvaluation,
) -> dict[str, object]:
    assessment = assess_candidate(study, reference, evaluation, confirmation=False)
    comparison = assessment.comparison
    parameter = next(p for p in study.parameter_space.parameters if p.name == point.parameter)
    boundary = point.value in {parameter.lower, parameter.upper}
    interpretation = "inconclusive or regressing"
    if not assessment.reasons:
        interpretation = (
            "promising development result; investigate boundary"
            if boundary
            else "promising development result"
        )
    return {
        "parameter": point.parameter,
        "value": point.value,
        "configuration_digest": point.configuration_digest,
        "score": comparison.candidate_score,
        "difference": comparison.mean_difference,
        "lower": comparison.interval.lower,
        "upper": comparison.interval.upper,
        "at_boundary": boundary,
        "interpretation": interpretation,
        "assessment": record_to_dict(assessment),
    }


def _evaluate_stage(
    study: StudySpec,
    points: tuple[SweepPoint, ...],
    template: RunManifest,
    root: Path,
    repository: Path,
    *,
    recheck: bool,
    recover_lock: bool,
) -> list[dict[str, object]]:
    store = StudyStore(root)
    rows: list[dict[str, object]] = []
    status = "running"
    with store.writer(recover_lock=recover_lock):
        store.prepare(
            {
                "study": record_to_dict(study),
                "points": [record_to_dict(p) for p in points],
                "suite": record_to_dict(template),
            }
        )
        try:
            reference = evaluate_recorded_candidate(
                store, study, template, study.incumbent, repository_root=repository
            )
            if not reference.report.optimization_evidence:
                raise SpecError("Incumbent evidence is invalid; range investigation stopped.")
            if not recheck:
                write_benchmark(root.parent / "benchmark", reference)
            for index, point in enumerate(points):
                advance(f"{point.parameter}={point.value:g} ({index + 1}/{len(points)})")
                evaluation = evaluate_recorded_candidate(
                    store,
                    study,
                    template,
                    study.bind(point.coordinates),
                    repository_root=repository,
                )
                if not evaluation.report.optimization_evidence:
                    raise SpecError("Candidate evidence is invalid; range investigation stopped.")
                rows.append(summarize_point(study, point, reference, evaluation))
                write_stage_report(root, study, rows, len(points), recheck=recheck, status=status)
            store.finish()
            status = "complete"
        except BaseException as error:
            status = (
                "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
            )
            raise
        finally:
            write_stage_report(root, study, rows, len(points), recheck=recheck, status=status)
    return rows


def run_ranges(protocol: Path, root: Path, *, recover_lock: bool = False) -> None:
    repository = default_repository_root()
    study, multipliers = load_protocol(protocol, repository)
    if (
        study.mode is not StudyMode.SCIENTIFIC
        or not study.optimization.repository.is_clean_checkout
    ):
        raise SpecError(
            "Range investigation requires committed inputs and a clean scientific checkout."
        )
    validate_run_environment(study.optimization, repository_root=repository)
    points = sweep_points(study, multipliers)
    store = StudyStore(root)
    with store.writer(recover_lock=recover_lock):
        store.prepare(
            {
                "study": record_to_dict(study),
                "protocol": dict(read_record_mapping(protocol)),
                "multipliers": list(multipliers),
            }
        )
        _ = write_range_plan(study, points, root)
        sections = index_sections()
        write_report(
            root,
            "Benchmark and range investigation",
            "Investigation in progress; see each stage for completion and evidence.",
            {"status": "running"},
            sections,
        )
        try:
            with stage("range sensitivity"):
                sensitivity = run_sensitivity(
                    study, output_root=root / "sensitivity", repository_root=repository
                )
                require_sensitivity(study, sensitivity)
                write_report(
                    root / "sensitivity",
                    "Sensitivity",
                    (
                        "This checks that the parameter range changes decisions and "
                        "control outcomes. It does not establish stronger play."
                    ),
                    sensitivity.to_dict(),
                    [
                        (
                            "Weights",
                            table(
                                ["Weight", "Changed decisions", "Score witnesses"],
                                [
                                    (d.name, d.final_action_changes, d.relative_score_witnesses)
                                    for d in sensitivity.dimensions
                                ],
                            ),
                        )
                    ],
                )
            with stage("range screening"):
                screening = _evaluate_stage(
                    study,
                    points,
                    study.optimization,
                    root / "screening",
                    repository,
                    recheck=False,
                    recover_lock=recover_lock,
                )
            nominated = nominate_ranges(study, screening)
            _ = store.record(
                "nomination", {"configurations": list(nominated), "screening": screening}
            )
            recheck_points = tuple(p for p in points if p.configuration_digest in nominated)
            rechecks: list[dict[str, object]] = []
            if recheck_points:
                with stage("range recheck"):
                    rechecks = _evaluate_stage(
                        study,
                        recheck_points,
                        study.validation,
                        root / "recheck",
                        repository,
                        recheck=True,
                        recover_lock=recover_lock,
                    )
            else:
                write_stage_report(
                    root / "recheck",
                    study,
                    (),
                    0,
                    recheck=True,
                    status="not_required_no_screening_gain",
                )
            _ = store.record("complete", {"rechecks": rechecks})
            store.finish()
            write_report(
                root,
                "Benchmark and range investigation",
                (
                    "Complete. Read screening and recheck together. No held-out games "
                    "were used and no policy was promoted."
                ),
                {
                    "status": "complete",
                    "plan": write_range_plan(study, points, root),
                    "screening": screening,
                    "rechecks": rechecks,
                    "held_out_games": 0,
                },
                index_sections(rechecks),
            )
        except BaseException as error:
            status = (
                "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
            )
            write_report(
                root,
                "Benchmark and range investigation",
                str(error) or status,
                {"status": status, "detail": str(error)},
                sections,
            )
            raise


def _read_stage(
    study: StudySpec,
    points: tuple[SweepPoint, ...],
    template: RunManifest,
    root: Path,
    *,
    recheck: bool,
) -> list[dict[str, object]]:
    """Rebuild from committed evaluations, without execution or current-source checks."""
    if not (root / "snapshot.json").exists():
        return []
    store = StudyStore(root, verification_only=True)
    rows: list[dict[str, object]] = []
    with store.writer():
        store.prepare(
            {
                "study": record_to_dict(study),
                "points": [record_to_dict(p) for p in points],
                "suite": record_to_dict(template),
            }
        )
        configurations = [study.incumbent, *(study.bind(p.coordinates) for p in points)]
        reference = None
        for index, entry in enumerate(store.entries):
            if entry.kind != "evaluation" or index >= len(configurations):
                raise RunConflictError("Unexpected range evaluation journal entry.")
            loaded = RunStore.from_root(root / cast(str, entry.payload["run_root"])).load()
            expected = candidate_manifest(
                template, configurations[index], run_id=loaded.manifest.run_id
            )
            if (
                loaded.manifest != expected
                or dict(loaded.result_digests) != entry.payload["results"]
            ):
                raise RunConflictError("Range evidence differs from its frozen evaluation.")
            evaluation = RecordedEvaluation(
                loaded, build_run_report(loaded, bootstrap=study.bootstrap)
            )
            if not evaluation.report.optimization_evidence:
                write_stage_report(root, study, rows, len(points), recheck=recheck, status="failed")
                return rows
            if index == 0:
                reference = evaluation
                if not recheck:
                    write_benchmark(root.parent / "benchmark", reference)
            else:
                assert reference is not None
                rows.append(summarize_point(study, points[index - 1], reference, evaluation))
    write_stage_report(
        root,
        study,
        rows,
        len(points),
        recheck=recheck,
        status="complete" if len(rows) == len(points) else "incomplete",
    )
    return rows


def rebuild_range_reports(root: Path) -> None:
    snapshot = cast(Mapping[str, object], read_checked_document(root / "snapshot.json")["snapshot"])
    study = study_from_dict(snapshot["study"])
    multipliers = tuple(
        finite_float(v, context="multiplier") for v in cast(list[object], snapshot["multipliers"])
    )
    points = sweep_points(study, multipliers)
    store = StudyStore(root, verification_only=True)
    with store.writer():
        store.prepare(snapshot)
        plan = write_range_plan(study, points, root)
        screening = _read_stage(
            study, points, study.optimization, root / "screening", recheck=False
        )
        nomination = next(
            (entry.payload for entry in store.entries if entry.kind == "nomination"), None
        )
        nominated = (
            () if nomination is None else tuple(cast(list[str], nomination["configurations"]))
        )
        if nomination is not None and (
            nomination["screening"] != screening or nominated != nominate_ranges(study, screening)
        ):
            raise RunConflictError("Range nomination differs from verified screening evidence.")
        rechecks = _read_stage(
            study,
            tuple(p for p in points if p.configuration_digest in nominated),
            study.validation,
            root / "recheck",
            recheck=True,
        )
        complete = next(
            (entry.payload for entry in store.entries if entry.kind == "complete"), None
        )
        if complete is not None and complete["rechecks"] != rechecks:
            raise RunConflictError("Range completion differs from verified recheck evidence.")
        write_report(
            root,
            "Benchmark and range investigation",
            "Reports rebuilt from frozen evidence; no games played.",
            {
                "status": "complete" if complete is not None else "incomplete",
                "plan": plan,
                "screening": screening,
                "rechecks": rechecks,
                "held_out_games": 0,
            },
            index_sections(rechecks),
        )


def ranges_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("action", choices=("plan", "run", "report"), nargs="?", default="run")
    _ = parser.add_argument(
        "--protocol",
        type=Path,
        default=Path(
            os.environ.get("GWENT_RANGE_PROTOCOL")
            or default_repository_root() / "experiments/tuning/ranges.json"
        ),
    )
    _ = parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            os.environ.get("GWENT_RANGE_OUTPUT_ROOT")
            or default_repository_root() / ".output/ranges"
        ),
    )
    _ = parser.add_argument("--recover-lock", action="store_true")
    parser.set_defaults(handler=range_command)
    return parser


def range_command(args: argparse.Namespace) -> int:
    protocol, root = cast(Path, args.protocol), cast(Path, args.output)
    action = cast(str, args.action)
    if action == "plan":
        study, multipliers = load_protocol(protocol, default_repository_root())
        plan = write_range_plan(study, sweep_points(study, multipliers), root)
        print(
            f"Screening: {plan['screening_games']:,} games; "
            + f"recheck ≤{plan['maximum_recheck_games']:,}; held-out: 0."
        )
    elif action == "report":
        rebuild_range_reports(root)
    else:
        with TerminalProgress(sys.stderr).display():
            run_ranges(protocol, root, recover_lock=cast(bool, args.recover_lock))
    print(f"Read: {root / ('plan/report.html' if action == 'plan' else 'report.html')}")
    return 0


def main() -> None:
    _ = range_command(ranges_parser().parse_args())


if __name__ == "__main__":
    main()
