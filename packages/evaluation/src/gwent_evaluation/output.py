"""Reading guides for disposable results; executable code stays in the repository."""

from pathlib import Path
from urllib.parse import quote

from gwent_evaluation.storage import atomic_write_text

RUN_FILES = """| File family | Meaning |
| --- | --- |
| `manifest.json` | Frozen suite, agents, source commit, runtime, assets, and identity. |
| `schedule.jsonl` | One scheduled case per line, including seeds and seats. |
| `matches/*.json` | Checksummed outcomes; these are authoritative match evidence. |
| `evidence/*.samples.jsonl` | Player-safe decision samples, when collected. |
| `evidence/*.trajectory.json` | Replay trajectories when the evidence policy retains them. |
| `report.json`, `report.md` | Derived summaries of the verified match records. |

Digest-based case names bind evidence to its scheduled case. Do not rename or
edit committed evidence. Summary-only runs have no decision samples or trajectories.
"""


def write_run_guide(root: Path) -> None:
    atomic_write_text(
        root / "README.md",
        "# Evaluation run\n\nOpen [report.md](report.md) for results. "
        + "[manifest.json](manifest.json) records the inputs.\n\n"
        + RUN_FILES,
    )


def write_sensitivity_guide(root: Path) -> None:
    atomic_write_text(
        root / "README.md",
        "# Sensitivity evidence\n\n"
        + "[report.json](report.json) explains whether the weight surface changes "
        + "relative action scores, selected actions, and match outcomes. Passing does "
        + "not prove improved strength or optimal bounds.\n\n"
        + "[snapshot.json](snapshot.json) freezes the study. `runs/` contains the "
        + "incumbent and bound-control evaluations. Decision samples are required "
        + "for rescoring; full trajectories are retained for failures.\n\n"
        + RUN_FILES,
    )


def write_output_index(root: Path) -> None:
    """Index existing guides only; never advertise missing or half-written reports."""
    links = [
        f"- [{path.name}]({quote(path.name)}/README.md)"
        for path in sorted(root.iterdir())
        if path.is_dir() and (path / "README.md").is_file()
    ]
    atomic_write_text(
        root / "README.md",
        "# Experiment results\n\n"
        + "These are disposable generated results. Source, commands, and authored "
        + "inputs live in the repository. `make pilot` creates or resumes the complete "
        + "pilot; separately requested experiments live under `manual/`.\n\n"
        + "\n".join(links)
        + "\n",
    )
