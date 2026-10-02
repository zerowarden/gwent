"""Bounded candidate-only timing on identical recorded, player-safe observations."""

from pathlib import Path
from time import perf_counter

from gwent_engine.ai.arena.catalog import create_bot
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_engine.serialize.actions import action_from_id
from gwent_shared.json_payloads import canonical_digest

from gwent_evaluation.assets import resolve_assets
from gwent_evaluation.execution import validate_run_environment
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import sample_observations
from gwent_evaluation.tuning.storage import read_checked_document, write_checked_document


def measure_selected_latency(
    study: StudySpec, selected: HeuristicConfiguration, *, root: Path, repository_root: Path
) -> None:
    """No new games or optimizer feedback; timings never change strategic fitness."""
    path = root / "latency.json"
    if path.exists():
        return
    store = RunStore.from_root(root / "sensitivity/runs/incumbent")
    loaded = store.load()
    sampled = store.load(sample_cases=tuple(loaded.results))
    observations = sample_observations(sampled, study.sensitivity.observations_per_match)
    assets = resolve_assets()
    bots = tuple(
        create_bot("heuristic", bot_id=name, heuristic_configuration=config)
        for name, config in (("incumbent", study.incumbent), ("selected", selected))
    )
    durations: tuple[list[float], list[float]] = ([], [])
    validate_run_environment(study.optimization, repository_root=repository_root)
    for index, case in enumerate(observations):
        sample = case.sample
        actions = tuple(action_from_id(value) for value in sample.legal_option_ids)
        # Alternate ordering to reduce consistent warm-cache advantage.
        for slot in (0, 1) if index % 2 == 0 else (1, 0):
            start = perf_counter()
            _ = bots[slot].choose_action(
                sample.observation,
                actions,
                card_registry=assets.card_registry,
                leader_registry=assets.leader_registry,
            )
            durations[slot].append(perf_counter() - start)
    validate_run_environment(study.optimization, repository_root=repository_root)
    _ = write_checked_document(
        path,
        {
            "study_digest": study.digest(),
            "selected_digest": selected.digest(),
            "observations_digest": canonical_digest(
                tuple(case.identity() for case in observations)
            ),
            "protocol": "alternating incumbent/selected choose_action on sensitivity observations",
            "configurations": [
                {
                    "role": role,
                    "configuration_digest": config.digest(),
                    "samples": len(values),
                    "mean_seconds": sum(values) / len(values) if values else None,
                    "durations_seconds": values,
                }
                for role, config, values in zip(
                    ("incumbent", "selected"), (study.incumbent, selected), durations, strict=True
                )
            ],
        },
    )


def load_latency(root: Path, study: StudySpec) -> dict[str, object] | None:
    if not (root / "latency.json").exists():
        return None
    payload = read_checked_document(root / "latency.json")
    if payload["study_digest"] != study.digest():
        raise RunConflictError("Latency diagnostics belong to another study.")
    return dict(payload)
