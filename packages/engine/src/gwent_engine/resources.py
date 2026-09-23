from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def bundled_data_dir() -> Path:
    return Path(str(files("gwent_engine").joinpath("data")))


def bundled_data_path(filename: str) -> Path:
    return bundled_data_dir() / filename
