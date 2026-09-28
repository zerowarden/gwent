from io import StringIO
from typing import override

import pytest
from gwent_evaluation.progress import Progress, TerminalProgress, advance, observe, stage


def test_progress_is_scoped_and_reports_stopped_stage() -> None:
    events: list[Progress] = []
    with observe(events.append):
        with pytest.raises(KeyboardInterrupt), stage("validation"):
            advance("candidate", completed=3, total=12)
            raise KeyboardInterrupt
    before = len(events)
    advance("outside observer")
    assert len(events) == before
    assert [event.stage for event in events] == ["validation"] * 3
    assert events[1].completed == 3
    assert events[-1].detail.startswith("stopped")


def test_redirected_progress_is_sparse_and_has_no_terminal_escapes() -> None:
    stream = StringIO()
    progress = TerminalProgress(stream)
    with progress.display(), stage("optimization"):
        for count in range(101):
            advance("candidate", completed=count, total=100)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 7
    assert "100/100" in lines[-2]
    assert "\x1b" not in stream.getvalue()


def test_terminal_progress_cleans_up_display_on_exception() -> None:
    class Terminal(StringIO):
        @override
        def isatty(self) -> bool:
            return True

    stream = Terminal()
    with pytest.raises(ValueError), TerminalProgress(stream).display(), stage("test"):
        raise ValueError("stopped")
    assert "\r\x1b[2Ktest: stopped" in stream.getvalue()
