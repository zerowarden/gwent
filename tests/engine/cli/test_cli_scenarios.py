from pathlib import Path
from typing import cast

import pytest
from gwent_engine.cli.report.models import build_report_context
from gwent_engine.cli.scenario_loader import load_scenario_path
from gwent_engine.cli.scenarios import run_loaded_scenario
from gwent_engine.core.errors import DefinitionLoadError

from tests.engine.support import CARD_REGISTRY, LEADER_REGISTRY
from tests.support import write_yaml_fixture


def test_loader_rejects_duplicate_card_aliases(
    tmp_path: Path,
) -> None:
    scenario_path = write_yaml_fixture(
        tmp_path,
        "duplicate_alias.yaml",
        """
id: duplicate_alias
players:
  p1:
    leader_id: scoiatael_francesca_the_beautiful
    deck:
      - alias: shared_alias
        card_id: scoiatael_mahakaman_defender
  p2:
    leader_id: scoiatael_francesca_the_beautiful
    deck:
      - alias: shared_alias
        card_id: scoiatael_dol_blathanna_archer
steps:
  - type: start_game
""",
    )

    with pytest.raises(DefinitionLoadError, match="shared_alias"):
        _ = load_scenario_path(
            scenario_path,
            leader_registry=LEADER_REGISTRY,
        )


def test_leave_step_still_produces_final_round_summary(tmp_path: Path) -> None:
    scenario_path = tmp_path / "leave_match.yaml"
    p1_deck = "\n".join(
        f"      - alias: p1_archer_{index}\n        card_id: scoiatael_dol_blathanna_archer"
        for index in range(1, 11)
    )
    p2_deck = "\n".join(
        f"      - alias: p2_defender_{index}\n        card_id: scoiatael_mahakaman_defender"
        for index in range(1, 11)
    )
    _ = scenario_path.write_text(
        f"""
id: leave_match
players:
  p1:
    leader_id: scoiatael_francesca_the_beautiful
    deck:
{p1_deck}
  p2:
    leader_id: scoiatael_francesca_the_beautiful
    deck:
{p2_deck}
steps:
  - type: start_game
  - type: leave
    player: p1
""".strip(),
        encoding="utf-8",
    )
    run = run_loaded_scenario(
        load_scenario_path(
            scenario_path,
            leader_registry=LEADER_REGISTRY,
            scenario_name="leave_match",
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    context = build_report_context(
        run,
        player_one_bot_spec="scenario",
        player_two_bot_spec="scenario",
        seed=0,
    )
    steps = cast(tuple[dict[str, object], ...], context["steps"])

    assert cast(dict[str, object], steps[-1]["round_summary"]) is not None
    assert cast(dict[str, object], steps[-1]["round_summary"])["round_number"] == 1
