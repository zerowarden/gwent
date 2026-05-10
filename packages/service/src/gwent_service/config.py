from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    data_dir: Path
    cards_path: Path
    sample_decks_path: Path
    leaders_path: Path
    repository_backend: str
    sqlite_path: Path


def default_service_config() -> ServiceConfig:
    workspace_root = Path(__file__).resolve().parents[4]
    data_dir = workspace_root / "data"
    return ServiceConfig(
        data_dir=data_dir,
        cards_path=data_dir / "cards.yaml",
        sample_decks_path=data_dir / "sample_decks.yaml",
        leaders_path=data_dir / "leaders.yaml",
        repository_backend=getenv("GWENT_SERVICE_REPOSITORY", "memory"),
        sqlite_path=Path(
            getenv(
                "GWENT_SERVICE_SQLITE_PATH",
                str(workspace_root / "gwent_service.sqlite3"),
            )
        ),
    )
