from __future__ import annotations

import json
from pathlib import Path

from gwent_engine.cli.models import CliRun
from gwent_engine.cli.report.audit import build_bot_match_audit_payload
from gwent_engine.cli.report.format import HTMLFormatter
from gwent_engine.cli.report.models import build_report_context
from gwent_engine.cli.report.writer import ReportWriter

DEFAULT_REPORT_DIR = Path(".output")


def write_bot_match_review(
    run: CliRun,
    *,
    player_one_bot_spec: str,
    player_two_bot_spec: str,
    seed: int,
    output_dir: Path = DEFAULT_REPORT_DIR,
) -> Path:
    title = f"{player_one_bot_spec} vs {player_two_bot_spec}"
    generated_at = HTMLFormatter.generated_at()
    context: dict[str, object] = {
        "match": build_report_context(
            run,
            player_one_bot_spec=player_one_bot_spec,
            player_two_bot_spec=player_two_bot_spec,
            seed=seed,
        )
    }
    bundle_dir = output_dir / _report_dirname(
        player_one_bot_spec=player_one_bot_spec,
        player_two_bot_spec=player_two_bot_spec,
        seed=seed,
    )
    writer = ReportWriter(output_dir=bundle_dir)
    report_path = writer.write(
        filename="report.html",
        template_name="match_review.html.j2",
        title=title,
        context=context,
        generated_at=generated_at,
    )
    _ = (bundle_dir / "report.json").write_text(
        json.dumps(
            build_bot_match_audit_payload(
                run,
                player_one_bot_spec=player_one_bot_spec,
                player_two_bot_spec=player_two_bot_spec,
                seed=seed,
                generated_at=generated_at,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report_path


def render_bot_match_review_html(
    run: CliRun,
    *,
    player_one_bot_spec: str,
    player_two_bot_spec: str,
    seed: int,
) -> str:
    return ReportWriter(output_dir=DEFAULT_REPORT_DIR).render(
        template_name="match_review.html.j2",
        title=f"{player_one_bot_spec} vs {player_two_bot_spec}",
        context={
            "match": build_report_context(
                run,
                player_one_bot_spec=player_one_bot_spec,
                player_two_bot_spec=player_two_bot_spec,
                seed=seed,
            )
        },
    )


def _report_dirname(
    *,
    player_one_bot_spec: str,
    player_two_bot_spec: str,
    seed: int,
) -> str:
    del player_one_bot_spec, player_two_bot_spec, seed
    return f"{HTMLFormatter.timestamp()}_match_review"
