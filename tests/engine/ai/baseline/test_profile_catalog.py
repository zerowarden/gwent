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

    assert "neutral" in profile_ids
    assert "conservative" in profile_ids
    assert "aggressive" in profile_ids
    assert "baseline" not in profile_ids
    assert "aggro" not in profile_ids
    assert "tempo" not in profile_ids


def test_get_base_profile_definition_returns_loaded_profile() -> None:
    profile = get_base_profile_definition("conservative")

    assert profile.profile_id == "conservative"
    assert profile.policies.scorch_policy == "reserve_scorch"
    assert profile.weights.card_advantage == 2.2
    assert profile.pass_overrides.safe_lead_margin == 5


@pytest.mark.parametrize("legacy_profile_id", ["tempo", "baseline", "aggro"])
def test_get_base_profile_definition_rejects_legacy_profile_ids(
    legacy_profile_id: str,
) -> None:
    with pytest.raises(ValueError, match="Unknown profile id"):
        _ = get_base_profile_definition(legacy_profile_id)


def test_default_base_profile_matches_neutral_yaml_profile() -> None:
    profile = get_base_profile_definition("neutral")

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
