"""Invocation-local progress observations, separate from persisted scientific evidence."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from shutil import get_terminal_size
from threading import Event, Thread
from typing import TextIO, final


@dataclass(frozen=True, slots=True)
class Progress:
    stage: str
    detail: str = ""
    completed: int | None = None
    total: int | None = None


_observer: ContextVar[Callable[[Progress], None] | None] = ContextVar("progress", default=None)
_stage: ContextVar[str] = ContextVar("progress_stage", default="evaluation")


def advance(detail: str, *, completed: int | None = None, total: int | None = None) -> None:
    observer = _observer.get()
    if observer is not None:
        observer(Progress(_stage.get(), detail, completed, total))


@contextmanager
def stage(name: str) -> Generator[None]:
    token = _stage.set(name)
    advance("starting")
    try:
        yield
    except BaseException:
        advance("stopped; recorded work is preserved")
        raise
    else:
        advance("complete")
    finally:
        _stage.reset(token)


@contextmanager
def observe(callback: Callable[[Progress], None]) -> Generator[None]:
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


@final
class TerminalProgress:
    """TTY spinner with match bars; sparse, escape-free stage updates in logs."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.current = Progress("preflight", "resolving inputs")
        self._last_log: tuple[str, str, int | None] | None = None
        self._frame = 0

    def update(self, event: Progress) -> None:
        self.current = event
        if self.stream.isatty():
            return
        bucket = None
        if event.completed is not None and event.total:
            bucket = event.completed * 4 // event.total
        key = (event.stage, event.detail, bucket)
        if key != self._last_log:
            print(self.render(event), file=self.stream, flush=True)
            self._last_log = key

    def render(self, event: Progress) -> str:
        bar = ""
        if event.completed is not None and event.total:
            filled = min(20, event.completed * 20 // event.total)
            bar = f" [{'#' * filled}{'-' * (20 - filled)}] {event.completed}/{event.total}"
        return f"{event.stage}{bar}: {event.detail}"

    @contextmanager
    def display(self) -> Generator[None]:
        stopped = Event()

        def animate() -> None:
            while not stopped.wait(0.15):
                frame = "|/-\\"[self._frame % 4]
                self._frame += 1
                line = self.render(self.current)[: max(10, get_terminal_size().columns - 3)]
                print(
                    f"\r\033[2K{frame} {line}",
                    end="",
                    file=self.stream,
                    flush=True,
                )

        thread = Thread(target=animate, daemon=True) if self.stream.isatty() else None
        if thread is not None:
            thread.start()
        try:
            with observe(self.update):
                yield
        finally:
            stopped.set()
            if thread is not None:
                thread.join()
                print(f"\r\033[2K{self.render(self.current)}", file=self.stream, flush=True)
