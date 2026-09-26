from __future__ import annotations

from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena.catalog import bot_family


def parse_bot_spec(spec: str) -> tuple[str, str | None]:
    normalized = spec.strip().lower()
    family, separator, profile_id = normalized.partition(":")
    if separator and not profile_id.strip():
        raise ValueError(f"Unknown bot spec: {spec!r}")
    return family, profile_id.strip() or None


def create_bot(
    spec: str,
    *,
    bot_id: str,
    seed: int | None = None,
) -> BotAgent:
    family, profile_id = parse_bot_spec(spec)
    return bot_family(family).build(
        bot_id=bot_id,
        profile_id=profile_id,
        seed=seed,
    )


def create_seeded_bot(
    spec: str,
    *,
    bot_id: str,
    seed: int | None = None,
) -> BotAgent:
    """Create a bot, applying the seed only when its family supports one."""

    family, profile_id = parse_bot_spec(spec)
    return bot_family(family).build_seeded(
        bot_id=bot_id,
        profile_id=profile_id,
        seed=seed,
    )
