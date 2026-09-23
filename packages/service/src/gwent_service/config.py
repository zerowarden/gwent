from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path

from gwent_engine.resources import bundled_data_path


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    cards_path: Path
    sample_decks_path: Path
    leaders_path: Path
    repository_backend: str
    sqlite_path: Path


def default_service_config() -> ServiceConfig:
    return ServiceConfig(
        cards_path=bundled_data_path("cards.yaml"),
        sample_decks_path=bundled_data_path("sample_decks.yaml"),
        leaders_path=bundled_data_path("leaders.yaml"),
        repository_backend=getenv("GWENT_SERVICE_REPOSITORY", "memory"),
        sqlite_path=Path(getenv("GWENT_SERVICE_SQLITE_PATH", "gwent_service.sqlite3")),
    )
