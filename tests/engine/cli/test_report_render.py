from __future__ import annotations

from pathlib import Path

from gwent_engine.cli.bot_matches import run_bot_match_cli
from gwent_engine.cli.report import write_bot_match_review


def test_write_bot_match_review_renders_diagnostic_panels(tmp_path: Path) -> None:
    run = run_bot_match_cli(
        player_one_bot_spec="heuristic:neutral",
        player_two_bot_spec="greedy",
        seed=5,
        include_bot_explanations=True,
    )

    report_path = write_bot_match_review(
        run,
        player_one_bot_spec="heuristic:neutral",
        player_two_bot_spec="greedy",
        seed=5,
        output_dir=tmp_path,
    )
    html = report_path.read_text(encoding="utf-8")
    audit = (report_path.parent / "report.json").read_text(encoding="utf-8")

    for marker in (
        'id="match-trace"',
        'class="action-badge"',
        "Mulligan Review",
        "Bot Debug",
        "round-summary-panel",
        "Board State at",
        'id="match-timeline"',
    ):
        assert marker in html
    assert '"step_kind"' in audit
