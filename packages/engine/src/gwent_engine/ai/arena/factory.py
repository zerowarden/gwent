from __future__ import annotations

from typing import Protocol

from gwent_shared.error_translation import translate_mapping_key

from gwent_engine.ai.agents import BotAgent, GreedyBot, RandomBot
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.search import SearchBot


def parse_bot_spec(spec: str) -> tuple[str, str | None]:
    normalized = spec.strip().lower()
    family, separator, profile_id = normalized.partition(":")
    if separator and not profile_id.strip():
        raise ValueError(f"Unknown bot spec: {spec!r}")
    return family, profile_id.strip() or None


def _build_random_bot(*, bot_id: str, seed: int | None, profile_id: str | None) -> BotAgent:
    del profile_id
    return RandomBot(seed=seed, bot_id=bot_id)


def _build_greedy_bot(*, bot_id: str, seed: int | None, profile_id: str | None) -> BotAgent:
    del seed, profile_id
    return GreedyBot(bot_id=bot_id)


class BotBuilder(Protocol):
    def __call__(
        self,
        *,
        bot_id: str,
        seed: int | None,
        profile_id: str | None,
    ) -> BotAgent: ...


class ProfiledBotFactory(Protocol):
    def __call__(self, *, bot_id: str, profile_id: str | None) -> BotAgent: ...


def _build_seedless_profiled_bot(
    bot_factory: ProfiledBotFactory,
    *,
    bot_id: str,
    seed: int | None,
    profile_id: str | None,
) -> BotAgent:
    del seed
    return bot_factory(bot_id=bot_id, profile_id=profile_id)


def _profiled_bot_builder(bot_factory: ProfiledBotFactory) -> BotBuilder:
    def build(*, bot_id: str, seed: int | None, profile_id: str | None) -> BotAgent:
        return _build_seedless_profiled_bot(
            bot_factory,
            bot_id=bot_id,
            seed=seed,
            profile_id=profile_id,
        )

    return build


BOT_BUILDERS: dict[str, BotBuilder] = {
    "random": _build_random_bot,
    "greedy": _build_greedy_bot,
    "heuristic": _profiled_bot_builder(HeuristicBot.from_profile_id),
    "search": _profiled_bot_builder(SearchBot.from_profile_id),
}


def create_bot(
    spec: str,
    *,
    bot_id: str,
    seed: int | None = None,
) -> BotAgent:
    family, profile_id = parse_bot_spec(spec)
    builder = translate_mapping_key(
        BOT_BUILDERS,
        family,
        lambda _family: ValueError(f"Unknown bot spec: {spec!r}"),
    )
    return builder(
        bot_id=bot_id,
        seed=seed,
        profile_id=profile_id,
    )
