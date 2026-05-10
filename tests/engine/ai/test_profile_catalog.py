from pathlib import Path

import pytest
from gwent_engine.ai.baseline import (
    DEFAULT_BASE_PROFILE,
    available_base_profile_ids,
    get_base_profile_definition,
    load_base_profiles,
)
from gwent_engine.core.errors import DefinitionLoadError

from tests.support import write_yaml_fixture


def test_load_default_base_profiles_contains_expected_profiles() -> None:
    profile_ids = available_base_profile_ids()

    assert "baseline" in profile_ids
    assert "conservative" in profile_ids
    assert "aggro" in profile_ids
    assert "tempo" not in profile_ids


def test_get_base_profile_definition_returns_loaded_profile() -> None:
    profile = get_base_profile_definition("conservative")

    assert profile.profile_id == "conservative"
    assert profile.policies.scorch_policy == "reserve_scorch"
    assert profile.weights.card_advantage == 2.2
    assert profile.pass_overrides.safe_lead_margin == 5


def test_get_base_profile_definition_accepts_legacy_tempo_alias() -> None:
    profile = get_base_profile_definition("tempo")

    assert profile.profile_id == "aggro"


def test_default_base_profile_matches_baseline_yaml_profile() -> None:
    profile = get_base_profile_definition("baseline")

    assert profile == DEFAULT_BASE_PROFILE


def test_load_base_profiles_rejects_unknown_policy_name(tmp_path: Path) -> None:
    path = write_yaml_fixture(
        tmp_path,
        "heuristic_profiles.yaml",
        """
profiles:
  broken:
    policies:
      scorch_policy: not_real
      leader_policy: aggressive
""",
    )

    with pytest.raises(DefinitionLoadError, match="unknown policy"):
        _ = load_base_profiles(path)
