from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.search import SearchDecisionExplanation
from gwent_engine.cli.args import parse_args
from gwent_engine.cli.bot_matches import (
    available_leaders,
    available_sample_decks,
    run_bot_match_cli,
)
from gwent_engine.cli.interactive import BotMatchSelection
from gwent_engine.cli.main import main
from gwent_engine.cli.models import CliRun
from gwent_engine.cli.presenters import summarize_event
from gwent_engine.core import AbilityKind
from gwent_engine.core.events import SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId

type WriteBotMatchReview = Callable[..., Path]


def test_summarize_event_surfaces_global_scorch_targets() -> None:
    scorch_card_id = CardInstanceId("p2_scorch")
    scorched_card_id = CardInstanceId("p1_catapult")

    summary = summarize_event(
        SpecialCardResolvedEvent(
            event_id=14,
            player_id=PlayerId("p2"),
            card_instance_id=scorch_card_id,
            ability_kind=AbilityKind.SCORCH,
            discarded_card_instance_ids=(scorched_card_id, scorch_card_id),
        ),
        card_names_by_instance_id={
            scorch_card_id: "Scorch",
            scorched_card_id: "Catapult",
        },
        card_values_by_instance_id={
            scorch_card_id: 0,
            scorched_card_id: 8,
        },
    )

    assert "scorched [Catapult] (8)" in summary
    assert "Scorch" in summary
    assert "scorched [Scorch]" not in summary


@pytest.mark.parametrize("argv", ([], ["--mode", "bot-match"]))
def test_parse_args_uses_interactive_bot_match(argv: list[str]) -> None:
    args = parse_args(argv)

    assert cast(str, args.mode) == "bot-match"


def test_parse_args_rejects_removed_scenario_mode() -> None:
    with pytest.raises(SystemExit):
        _ = parse_args(["--mode", "scenario"])


def test_bot_match_cli_returns_structured_cli_run() -> None:
    run = run_bot_match_cli(
        player_one_bot_spec="greedy",
        player_two_bot_spec="random",
        seed=5,
    )

    assert run.scenario_name == "bot_match"
    assert run.steps
    assert run.metadata.player_one_actor == "GreedyBot"
    assert run.metadata.player_two_actor == "RandomBot"
    assert run.final_state.status.value == "match_ended"


def test_bot_match_cli_can_include_bot_explanations() -> None:
    run = run_bot_match_cli(
        player_one_bot_spec="heuristic",
        player_two_bot_spec="random",
        seed=5,
        include_bot_explanations=True,
    )

    assert any(step.bot_explanation is not None for step in run.steps)


def test_bot_match_cli_can_include_search_bot_explanations() -> None:
    run = run_bot_match_cli(
        player_one_bot_spec="search:baseline",
        player_two_bot_spec="random",
        seed=5,
        include_bot_explanations=True,
    )

    p1_step = next(
        step
        for step in run.steps
        if getattr(step.action, "player_id", None) == "p1" and step.bot_explanation is not None
    )

    assert isinstance(p1_step.bot_explanation, SearchDecisionExplanation)
    assert p1_step.bot_explanation.profile_id == "baseline"
    assert p1_step.bot_explanation.evaluations


def test_bot_match_cli_accepts_leader_overrides() -> None:
    decks = available_sample_decks()
    deck = next(deck for deck in decks if str(deck.deck_id) == "nilfgaard_spy_medic_control_strict")
    override_leader = next(
        leader
        for leader in available_leaders()
        if leader.faction == deck.faction and leader.leader_id != deck.leader_id
    )

    run = run_bot_match_cli(
        player_one_bot_spec="greedy",
        player_two_bot_spec="random",
        player_one_deck_id="nilfgaard_spy_medic_control_strict",
        player_one_leader_id=str(override_leader.leader_id),
        seed=5,
    )

    assert run.metadata.player_one_deck_id == deck.deck_id
    assert run.final_state.players[0].leader.leader_id == override_leader.leader_id
    assert run.steps


@pytest.mark.parametrize(
    ("argv", "report_path", "expected_output_parts"),
    (
        (
            [],
            Path("/tmp/interactive-bot-match/report.html"),
            ("/tmp/interactive-bot-match", "/tmp/interactive-bot-match/report.html"),
        ),
        (
            ["--mode", "bot-match"],
            Path("/tmp/greedy-random_3_20260419-000000.html"),
            ("/tmp/greedy-random_3_20260419-000000.html",),
        ),
    ),
)
def test_main_bot_match_prints_html_review_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    report_path: Path,
    expected_output_parts: tuple[str, ...],
) -> None:
    exit_code, output = _run_main_with_report(
        monkeypatch,
        capsys,
        argv=argv,
        report_path=report_path,
    )
    single_line_output = output.replace("\n", "")

    assert exit_code == 0
    for expected_output_part in expected_output_parts:
        assert expected_output_part in single_line_output


def _run_main_with_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    argv: list[str],
    report_path: Path,
) -> tuple[int, str]:
    monkeypatch.setattr(
        "gwent_engine.cli.main.prompt_bot_match_selection",
        _fake_prompt_bot_match_selection,
    )
    monkeypatch.setattr(
        "gwent_engine.cli.main.write_bot_match_review",
        _fake_write_bot_match_review(report_path),
    )
    exit_code = main(argv)
    return exit_code, capsys.readouterr().out


def _fake_prompt_bot_match_selection(
    *,
    decks: object,
    leaders: object,
) -> BotMatchSelection:
    _ = (decks, leaders)
    return BotMatchSelection(
        player_one_bot_spec="greedy",
        player_two_bot_spec="random",
        player_one_deck_id="monsters_muster_swarm_strict",
        player_two_deck_id="nilfgaard_spy_medic_control_strict",
        player_one_leader_id="monsters_eredin_commander_of_the_red_riders",
        player_two_leader_id="nilfgaard_emhyr_his_imperial_majesty",
        seed=3,
        starting_player="p1",
    )


def _fake_write_bot_match_review(report_path: Path) -> WriteBotMatchReview:
    def fake_write_bot_match_review(
        run: CliRun,
        *,
        player_one_bot_spec: str,
        player_two_bot_spec: str,
        seed: int,
    ) -> Path:
        _ = (run, player_one_bot_spec, player_two_bot_spec, seed)
        return report_path

    return fake_write_bot_match_review
