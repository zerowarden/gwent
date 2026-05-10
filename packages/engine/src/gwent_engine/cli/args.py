from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Run deterministic bot-vs-bot Gwent matches for developer inspection.")
    )
    _ = parser.add_argument(
        "--mode",
        choices=("bot-match",),
        default="bot-match",
        help="Run the interactive bot match builder.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
