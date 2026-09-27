from pathlib import Path
from typing import NoReturn

import pytest
from gwent_evaluation import execution
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.specs import load_study_spec

from tests.evaluation.support import REPOSITORY_ROOT


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "allow_match_execution: module runs real matches despite the workspace guard",
    )


@pytest.fixture(autouse=True)
def forbid_games(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "allow_match_execution" in request.keywords:
        return

    def unexpected(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Parameter/spec tests must execute zero matches")

    monkeypatch.setattr(execution, "execute_match", unexpected)


@pytest.fixture
def study_path() -> Path:
    return REPOSITORY_ROOT / "experiments/tuning/smoke.json"


@pytest.fixture
def study(study_path: Path) -> StudySpec:
    return load_study_spec(study_path, repository_root=REPOSITORY_ROOT)
