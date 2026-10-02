from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.arena import create_bot, load_policy_bot
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.baseline.policy_artifacts import (
    PolicyArtifact,
    PolicyArtifactError,
    PolicyStatus,
)
from gwent_shared.json_payloads import canonical_hexdigest, dump_pretty_json

from tests.engine.ai.support import (
    make_round_three_visible_win_state,
    sample_policy_artifact,
    verified_decision_plan,
)
from tests.engine.support import CARD_REGISTRY, LEADER_REGISTRY, choose_bot_response
from tests.support import PLAYER_ONE_ID


def test_reload_preserves_actual_decisions_and_weight_provenance(tmp_path: Path) -> None:
    artifact = sample_policy_artifact()
    path = tmp_path / "policy.json"
    _ = path.write_text(dump_pretty_json(artifact.to_dict()))
    direct = create_bot(
        "heuristic", bot_id="direct", heuristic_configuration=artifact.configuration
    )
    loaded = load_policy_bot(path, bot_id="loaded")
    assert isinstance(direct, HeuristicBot) and isinstance(loaded, HeuristicBot)
    reference = verified_decision_plan(direct)
    actual = verified_decision_plan(loaded)
    assert actual.chosen_action == reference.chosen_action
    assert actual.profile.weight_provenance == reference.profile.weight_provenance
    assert actual.ranked_actions == reference.ranked_actions
    weight = next(
        item for item in actual.profile.weight_provenance if item.name == "immediate_points"
    )
    assert weight.base_config == 3.125
    assert HeuristicConfiguration().baseline.weights.immediate_points == 1.0


def test_artifact_is_independent_of_study_and_optimizer_packages(tmp_path: Path) -> None:
    artifact = sample_policy_artifact()
    path = tmp_path / "standalone.json"
    _ = path.write_text(dump_pretty_json(artifact.to_dict()))
    code = """
import importlib.abc, json, sys
from pathlib import Path
sys.path[:] = json.loads(sys.argv[2])
class BlockOptimizer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'cma', 'numpy', 'gwent_evaluation'}:
            raise ImportError('Runtime must not import optimization packages')
sys.meta_path.insert(0, BlockOptimizer())
from gwent_engine.ai.arena import load_policy_bot
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.baseline.policy_artifacts import PolicyArtifact
artifact = PolicyArtifact.load(Path(sys.argv[1]))
bot = load_policy_bot(Path(sys.argv[1]), bot_id='loaded')
assert isinstance(bot, HeuristicBot)
assert bot.configuration.digest() == artifact.configuration_digest
assert bot.configuration.baseline.weights.immediate_points == 3.125
from tests.engine.ai.support import make_round_three_visible_win_state
from tests.engine.support import CARD_REGISTRY, LEADER_REGISTRY, PLAYER_ONE_ID, choose_bot_response
from gwent_engine.serialize.actions import action_to_id
action = choose_bot_response(bot, make_round_three_visible_win_state(), player_id=PLAYER_ONE_ID,
    card_registry=CARD_REGISTRY, leader_registry=LEADER_REGISTRY)
print(json.dumps(action_to_id(action)))
"""
    outcome = subprocess.run(
        [sys.executable, "-c", code, str(path), json.dumps(sys.path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    from gwent_engine.serialize.actions import action_to_id

    bot = create_bot("heuristic", bot_id="direct", heuristic_configuration=artifact.configuration)
    action = choose_bot_response(
        bot,
        make_round_three_visible_win_state(),
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    assert json.loads(outcome.stdout) == json.loads(json.dumps(action_to_id(action)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("family", "search"),
        ("schema_version", 999),
        ("schema_version", True),
        ("observation_contract_version", 999),
        ("configuration_contract_version", 999),
        ("configuration_digest", "wrong"),
        ("artifact_digest", "wrong"),
        ("status", "champion"),
    ],
)
def test_incompatible_or_tampered_artifacts_fail(field: str, value: object) -> None:
    payload = sample_policy_artifact().to_dict()
    payload[field] = value
    if field != "artifact_digest":
        del payload["artifact_digest"]
        payload["artifact_digest"] = "sha256:" + canonical_hexdigest(payload)
    with pytest.raises(PolicyArtifactError):
        _ = PolicyArtifact.from_dict(payload)


def test_payload_changes_and_unknown_fields_fail(tmp_path: Path) -> None:
    payload = sample_policy_artifact().to_dict()
    configuration = cast(dict[str, object], payload["configuration"])
    baseline = cast(dict[str, object], configuration["baseline"])
    weights = cast(dict[str, object], baseline["weights"])
    weights["immediate_points"] = 99.0
    with pytest.raises(PolicyArtifactError, match="digest"):
        _ = PolicyArtifact.from_dict(payload)
    with pytest.raises(PolicyArtifactError, match="fields"):
        _ = PolicyArtifact.from_dict({**sample_policy_artifact().to_dict(), "unknown": 1})
    path = tmp_path / "invalid.json"
    _ = path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(PolicyArtifactError, match="duplicate"):
        _ = PolicyArtifact.load(path)


def test_evidence_metadata_does_not_change_behavior_identity() -> None:
    first = sample_policy_artifact()
    second = replace(first, status=PolicyStatus.PROMOTED, evidence_digest="confirmation")
    assert first.configuration_digest == second.configuration_digest
    assert first.to_dict()["artifact_digest"] != second.to_dict()["artifact_digest"]
