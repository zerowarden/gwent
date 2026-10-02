"""One reproducible pilot: smoke, sensitivity, optimization, replay, and reports."""

import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import final

from gwent_shared.json_payloads import canonical_json, dump_pretty_json

from gwent_evaluation.agents import snapshot_suite
from gwent_evaluation.execution import (
    EvidencePolicy,
    execute_run,
    pin_manifest,
    validate_run_environment,
)
from gwent_evaluation.models import RunManifest, SpecError, SuitePurpose, TerminationReason
from gwent_evaluation.progress import stage
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.schedule import schedule_suite
from gwent_evaluation.specs import load_agent_catalog, load_suite_catalog
from gwent_evaluation.storage import (
    RunConflictError,
    atomic_write_text,
    write_output_index,
    write_run_guide,
    write_sensitivity_guide,
)
from gwent_evaluation.tuning.html import write_plan_html
from gwent_evaluation.tuning.latency import measure_selected_latency
from gwent_evaluation.tuning.models import StudyMode, StudySpec
from gwent_evaluation.tuning.reporting import render_pilot_readme, write_pilot_exports
from gwent_evaluation.tuning.selection import select_challenger
from gwent_evaluation.tuning.sensitivity import (
    SensitivityReport,
    require_sensitivity,
    run_sensitivity,
)
from gwent_evaluation.tuning.specs import load_study_spec, plan_study
from gwent_evaluation.tuning.storage import (
    exclusive_writer,
    read_checked_document,
    write_checked_document,
)
from gwent_evaluation.tuning.study import StudyResult, run_study
from gwent_evaluation.tuning.study_report import write_study_report

STAGES = ("plan", "smoke", "sensitivity", "optimization", "replay", "reports")


def load_pilot_inputs(repository_root: Path) -> tuple[StudySpec, RunManifest]:
    study = load_study_spec(
        repository_root / "experiments/tuning/pilot.json", repository_root=repository_root
    )
    agents = load_agent_catalog(repository_root / "experiments/agents.json")
    suites = load_suite_catalog(repository_root / "experiments/suites.json", agents=agents)
    smoke = pin_manifest(
        snapshot_suite(suites["smoke-v1"]), run_id="smoke", repository_root=repository_root
    )
    return study, smoke


def _freeze_inputs(root: Path, study: StudySpec, smoke: RunManifest) -> None:
    inputs = root / "inputs"
    documents = {"study.json": record_to_dict(study), "smoke.json": record_to_dict(smoke)}
    if inputs.exists():
        for name, payload in documents.items():
            if canonical_json(read_checked_document(inputs / name)) != canonical_json(payload):
                raise RunConflictError("Pilot inputs differ from the frozen workflow.")
        return
    if any((root / name).exists() for name in ("data", "workflow.json", "reports")):
        raise RunConflictError("Pilot evidence exists without committed inputs.")
    # Publish the input pair together, just as RunStore publishes its metadata.
    with TemporaryDirectory(prefix=".inputs-", dir=root) as temporary:
        staging = Path(temporary) / "inputs"
        for name, payload in documents.items():
            _ = write_checked_document(staging / name, payload)
        _ = staging.rename(inputs)


def _recorded_matches(root: Path) -> dict[str, int]:
    patterns = {
        "smoke": "data/smoke/matches/*.json",
        "sensitivity": "data/sensitivity/runs/*/matches/*.json",
        "optimization": "data/optimization/runs/*/matches/*.json",
    }
    return {stage: sum(1 for _ in root.glob(pattern)) for stage, pattern in patterns.items()}


@final
class _Progress:
    def __init__(
        self,
        root: Path,
        study: StudySpec,
        repository_root: Path,
        notify: Callable[[str], None] | None,
    ) -> None:
        self.root = root
        self.study = study
        self.repository_root = repository_root
        self.notify = notify
        self.stages: dict[str, str] = dict.fromkeys(STAGES, "pending")
        self.sensitivity: SensitivityReport | None = None
        self.result: StudyResult | None = None
        self.initial_matches = sum(_recorded_matches(root).values())

    def write(self, stage: str, status: str, detail: str | None = None) -> None:
        self.stages[stage] = status
        matches = _recorded_matches(self.root)
        payload = {
            "schema_version": 1,
            "study_digest": self.study.digest(),
            "repository_root": str(self.repository_root.resolve()),
            "stage": stage,
            "status": status,
            "stages": self.stages,
            "detail": detail,
            "matches": matches,
            "executed_this_invocation": sum(matches.values()) - self.initial_matches,
        }
        log = self.root / "logs/events.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            _ = handle.write(
                canonical_json({"at": datetime.now(UTC).isoformat(), **payload}) + "\n"
            )
        atomic_write_text(self.root / "workflow.json", dump_pretty_json(payload))
        atomic_write_text(
            self.root / "README.md",
            render_pilot_readme(
                self.study,
                self.stages,
                detail=detail,
                repository_root=self.repository_root,
                output_root=self.root,
                sensitivity=self.sensitivity,
                result=self.result,
            ),
        )
        if self.notify is not None:
            self.notify(f"{stage}: {status}" + (f" — {detail}" if detail else ""))

    @contextmanager
    def stage(self, name: str) -> Generator[None]:
        self.write(name, "running")
        try:
            yield
        except (KeyboardInterrupt, SystemExit):
            self.write(name, "interrupted", "Run the same command to resume.")
            raise
        except Exception as error:
            self.write(name, "failed", str(error))
            raise
        self.write(name, "complete")


def run_pilot(
    study: StudySpec,
    smoke: RunManifest,
    *,
    output_root: Path,
    repository_root: Path,
    recover_lock: bool = False,
    notify: Callable[[str], None] | None = None,
) -> StudyResult:
    """Run a fixed workflow; status and reports never substitute for evidence checks."""
    if (
        study.mode is not StudyMode.SCIENTIFIC
        or not study.optimization.repository.is_clean_checkout
    ):
        raise SpecError("The pilot requires a scientific study from a clean committed checkout.")
    if smoke.suite.purpose is not SuitePurpose.SMOKE or smoke.run_id != "smoke":
        raise SpecError("The workflow requires a smoke-purpose manifest named smoke.")
    if (smoke.repository, smoke.runtime) != (
        study.optimization.repository,
        study.optimization.runtime,
    ):
        raise RunConflictError("Smoke and optimization must use the same source and runtime.")
    validate_run_environment(study.optimization, repository_root=repository_root)
    validate_run_environment(smoke, repository_root=repository_root)
    with exclusive_writer(output_root, recover_lock=recover_lock):
        _freeze_inputs(output_root, study, smoke)
        progress = _Progress(output_root, study, repository_root, notify)
        with progress.stage("plan"):
            plan = {**plan_study(study), "smoke_matches": len(schedule_suite(smoke.suite))}
            atomic_write_text(output_root / "reports/plan.json", dump_pretty_json(plan))
        if output_root.parent.name == ".output":
            write_output_index(output_root.parent)
        with progress.stage("smoke"):
            execution = execute_run(
                suite=smoke.suite,
                run_id=smoke.run_id,
                output_root=output_root / "data",
                repository_root=repository_root,
                evidence_policy=EvidencePolicy.NONE,
                expected_manifest=smoke,
            )
            write_run_guide(execution.root)
            if any(
                result.termination is not TerminationReason.COMPLETED
                for result in execution.results
            ):
                raise SpecError("Smoke matches did not all complete; optimization was not started.")
        with progress.stage("sensitivity"):
            progress.sensitivity = run_sensitivity(
                study,
                output_root=output_root / "data/sensitivity",
                repository_root=repository_root,
            )
            write_sensitivity_guide(output_root / "data/sensitivity")
            require_sensitivity(study, progress.sensitivity)
        optimization = output_root / "data/optimization"
        with progress.stage("optimization"):
            result = run_study(
                study,
                output_root=optimization,
                repository_root=repository_root,
                sensitivity_report=progress.sensitivity,
                recover_lock=recover_lock,
            )
        with progress.stage("replay"):
            replay = run_study(
                study,
                output_root=optimization,
                repository_root=repository_root,
                sensitivity_report=progress.sensitivity,
            )
            if replay != result:
                raise RunConflictError("Completed study replay produced different results.")
        with progress.stage("reports"):
            write_pilot_exports(output_root / "reports", study, result)
            progress.result = result
        return result


def run_tuning(
    study: StudySpec,
    *,
    output_root: Path,
    repository_root: Path,
    recover_lock: bool = False,
) -> None:
    """Freeze inputs, run preflight and optimization, then freeze validation selection."""
    validate_run_environment(study.optimization, repository_root=repository_root)
    if study.mode is StudyMode.SCIENTIFIC and not study.optimization.repository.is_clean_checkout:
        raise SpecError("Scientific tuning requires a clean committed checkout.")
    with exclusive_writer(output_root, recover_lock=recover_lock):
        path = output_root / "study.json"
        payload = record_to_dict(study)
        if path.exists():
            if read_checked_document(path) != payload:
                raise RunConflictError(
                    "Study inputs changed; use a new study ID after code or spec changes."
                )
        else:
            if any(output_root.glob("*/snapshot.json")):
                raise RunConflictError("Study evidence exists without frozen inputs.")
            _ = write_checked_document(path, payload)
        active = "sensitivity"
        write_plan_html(study, output_root)
        atomic_write_text(
            output_root / "operation.json", dump_pretty_json({"status": "running", "stage": active})
        )
        try:
            with stage("sensitivity"):
                sensitivity = run_sensitivity(
                    study, output_root=output_root / "sensitivity", repository_root=repository_root
                )
            _ = write_study_report(output_root, destination=output_root / "stages/sensitivity")
            if study.mode is StudyMode.SMOKE:
                atomic_write_text(
                    output_root / "operation.json",
                    dump_pretty_json({"status": "complete", "stage": "diagnostic"}),
                )
                return
            require_sensitivity(study, sensitivity)
            active = "optimization"
            atomic_write_text(
                output_root / "operation.json",
                dump_pretty_json({"status": "running", "stage": active}),
            )
            with stage(active):
                _ = run_study(
                    study,
                    output_root=output_root / "optimization",
                    repository_root=repository_root,
                    sensitivity_report=sensitivity,
                    recover_lock=recover_lock,
                )
            _ = write_study_report(output_root, destination=output_root / "stages/optimization")
            active = "validation"
            atomic_write_text(
                output_root / "operation.json",
                dump_pretty_json({"status": "running", "stage": active}),
            )
            with stage(active):
                selection = select_challenger(
                    output_root / "optimization",
                    repository_root=repository_root,
                    recover_lock=recover_lock,
                )
            _ = write_study_report(output_root, destination=output_root / "stages/validation")
            if selection.selected is not None:
                active = "candidate latency"
                with stage(active):
                    measure_selected_latency(
                        study, selection.selected, root=output_root, repository_root=repository_root
                    )
            atomic_write_text(
                output_root / "operation.json",
                dump_pretty_json({"status": "complete", "stage": active}),
            )
        except BaseException as error:
            atomic_write_text(
                output_root / "operation.json",
                dump_pretty_json(
                    {
                        "status": "interrupted"
                        if isinstance(error, (KeyboardInterrupt, SystemExit))
                        else "failed",
                        "stage": active,
                        "detail": str(error) or "Interrupted; rerun the same command to resume.",
                    }
                ),
            )
            raise
        finally:
            original_error = sys.exc_info()[0]
            try:
                with stage("report"):
                    _ = write_study_report(output_root)
            except Exception:
                if original_error is None:
                    raise
