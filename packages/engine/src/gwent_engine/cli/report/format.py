from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from html import escape
from typing import final

from gwent_engine.cli.models import CliRun


@final
class HTMLFormatter:
    def __init__(self, run: CliRun) -> None:
        self._kind_by_name = {
            escape(run.card_names_by_instance_id[card_id]): run.card_kinds_by_instance_id.get(
                card_id,
                "unit",
            )
            for card_id in run.card_names_by_instance_id
        }
        self._spy_by_name = {
            escape(run.card_names_by_instance_id[card_id]): run.card_spy_by_instance_id.get(
                card_id,
                False,
            )
            for card_id in run.card_names_by_instance_id
        }
        self._medic_by_name = {
            escape(run.card_names_by_instance_id[card_id]): run.card_medic_by_instance_id.get(
                card_id,
                False,
            )
            for card_id in run.card_names_by_instance_id
        }
        self._scorch_by_name = {
            escape(run.card_names_by_instance_id[card_id]): run.card_scorch_by_instance_id.get(
                card_id,
                False,
            )
            for card_id in run.card_names_by_instance_id
        }

    @staticmethod
    def timestamp(moment: datetime | None = None) -> str:
        resolved = moment or datetime.now()
        return resolved.strftime("%Y%m%d-%H%M%S-%f")[:-3]

    @staticmethod
    def generated_at(moment: datetime | None = None) -> str:
        return (moment or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

    def fmt(self, value: str) -> str:
        escaped = escape(value)
        escaped = re.sub(r"\[([^\]]+)\]", self._card_badge_sub, escaped)
        escaped = re.sub(r"\b(p1)\b", r'<span class="p1">\1</span>', escaped)
        escaped = re.sub(r"\b(p2)\b", r'<span class="p2">\1</span>', escaped)
        return re.sub(r"\((\d+)\)", r'(<span class="value">\1</span>)', escaped)

    def _card_badge_sub(self, match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in self._kind_by_name:
            return f"[{name}]"
        kind = self._kind_by_name.get(name, "unit")
        spy_marker = " 🕵️" if self._spy_by_name.get(name, False) else ""
        medic_marker = " ⚕️" if self._medic_by_name.get(name, False) else ""
        scorch_marker = " 🔥" if self._scorch_by_name.get(name, False) else ""
        return (
            f'<span class="card card-{kind}">{name}{spy_marker}{medic_marker}{scorch_marker}</span>'
        )


def counter_text(label: str, counter: Counter[str]) -> str:
    pairs = [
        f"{key}={value}"
        for key, value in sorted(counter.items(), key=lambda item: (item[0], item[1]))
        if value > 0
    ]
    return f"{label}: {', '.join(pairs) if pairs else 'none'}"


def split_key_value(line: str) -> tuple[str, str]:
    if "=" in line:
        key, value = line.split("=", maxsplit=1)
        return key, value
    if ":" in line:
        key, value = line.split(":", maxsplit=1)
        return key, value.strip()
    return "detail", line
