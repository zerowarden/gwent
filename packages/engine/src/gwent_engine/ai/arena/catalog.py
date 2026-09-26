from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from gwent_engine.ai.agents import BotAgent, GreedyBot, RandomBot
from gwent_engine.ai.baseline import DEFAULT_BASE_PROFILE, HeuristicBot
from gwent_engine.ai.policy import (
    DEFAULT_BASELINE_CONFIG,
    DEFAULT_GREEDY_ACTION_POLICY,
    DEFAULT_MULLIGAN_POLICY,
    DEFAULT_SEARCH_CONFIG,
)
from gwent_engine.ai.search import SearchBot


class BotFamily(StrEnum):
    RANDOM = "random"
    GREEDY = "greedy"
    HEURISTIC = "heuristic"
    SEARCH = "search"


class BotConstructor(Protocol):
    def __call__(
        self,
        *,
        bot_id: str,
        profile_id: str | None,
        seed: int | None,
    ) -> BotAgent: ...


@dataclass(frozen=True, slots=True)
class BotFamilyDefinition:
    """Engine-owned capability descriptor for one bot implementation family.

    The definition is the single authority for how a family is constructed and
    which optional inputs it supports, so spec validation, CLI construction, and
    provenance all read the same surface.
    """

    family: BotFamily
    accepts_profile: bool
    accepts_seed: bool
    default_profile_id: str | None
    construct: BotConstructor
    fixed_configuration: object = None

    def __post_init__(self) -> None:
        if self.accepts_profile != (self.default_profile_id is not None):
            raise ValueError(
                "Bot families that accept a profile must declare a default profile id."
            )

    def build(
        self,
        *,
        bot_id: str,
        profile_id: str | None = None,
        seed: int | None = None,
    ) -> BotAgent:
        if profile_id is not None and not self.accepts_profile:
            raise ValueError(f"Bot family {self.family.value!r} does not accept a profile.")
        if seed is not None and not self.accepts_seed:
            raise ValueError(f"Bot family {self.family.value!r} does not accept a seed.")
        resolved_profile_id = profile_id
        if self.accepts_profile and resolved_profile_id is None:
            resolved_profile_id = self.default_profile_id
        return self.construct(
            bot_id=bot_id,
            profile_id=resolved_profile_id,
            seed=seed,
        )

    def build_seeded(
        self,
        *,
        bot_id: str,
        profile_id: str | None = None,
        seed: int | None = None,
    ) -> BotAgent:
        """Build with the seed applied only when the family declares seed support."""

        return self.build(
            bot_id=bot_id,
            profile_id=profile_id,
            seed=seed if self.accepts_seed else None,
        )


def _construct_random(
    *,
    bot_id: str,
    profile_id: str | None,
    seed: int | None,
) -> BotAgent:
    del profile_id
    return RandomBot(seed=seed, bot_id=bot_id)


def _construct_greedy(
    *,
    bot_id: str,
    profile_id: str | None,
    seed: int | None,
) -> BotAgent:
    del profile_id, seed
    return GreedyBot(bot_id=bot_id)


def _construct_heuristic(
    *,
    bot_id: str,
    profile_id: str | None,
    seed: int | None,
) -> BotAgent:
    del seed
    return HeuristicBot.from_profile_id(bot_id=bot_id, profile_id=profile_id)


def _construct_search(
    *,
    bot_id: str,
    profile_id: str | None,
    seed: int | None,
) -> BotAgent:
    del seed
    return SearchBot.from_profile_id(bot_id=bot_id, profile_id=profile_id)


_DEFAULT_PROFILE_ID = DEFAULT_BASE_PROFILE.profile_id
_GREEDY_FIXED_CONFIGURATION: Mapping[str, object] = MappingProxyType(
    {
        "action": DEFAULT_GREEDY_ACTION_POLICY,
        "mulligan": DEFAULT_MULLIGAN_POLICY,
    }
)
_HEURISTIC_FIXED_CONFIGURATION: Mapping[str, object] = MappingProxyType(
    {"baseline": DEFAULT_BASELINE_CONFIG}
)
_SEARCH_FIXED_CONFIGURATION: Mapping[str, object] = MappingProxyType(
    {
        "baseline": DEFAULT_BASELINE_CONFIG,
        "search": DEFAULT_SEARCH_CONFIG,
    }
)

_BOT_FAMILY_DEFINITIONS: tuple[BotFamilyDefinition, ...] = (
    BotFamilyDefinition(
        family=BotFamily.RANDOM,
        accepts_profile=False,
        accepts_seed=True,
        default_profile_id=None,
        construct=_construct_random,
        fixed_configuration=None,
    ),
    BotFamilyDefinition(
        family=BotFamily.GREEDY,
        accepts_profile=False,
        accepts_seed=False,
        default_profile_id=None,
        construct=_construct_greedy,
        fixed_configuration=_GREEDY_FIXED_CONFIGURATION,
    ),
    BotFamilyDefinition(
        family=BotFamily.HEURISTIC,
        accepts_profile=True,
        accepts_seed=False,
        default_profile_id=_DEFAULT_PROFILE_ID,
        construct=_construct_heuristic,
        fixed_configuration=_HEURISTIC_FIXED_CONFIGURATION,
    ),
    BotFamilyDefinition(
        family=BotFamily.SEARCH,
        accepts_profile=True,
        accepts_seed=False,
        default_profile_id=_DEFAULT_PROFILE_ID,
        construct=_construct_search,
        fixed_configuration=_SEARCH_FIXED_CONFIGURATION,
    ),
)

BOT_FAMILIES: Mapping[BotFamily, BotFamilyDefinition] = MappingProxyType(
    {definition.family: definition for definition in _BOT_FAMILY_DEFINITIONS}
)


def bot_family(family: str | BotFamily) -> BotFamilyDefinition:
    try:
        resolved = family if isinstance(family, BotFamily) else BotFamily(family)
    except ValueError as error:
        raise ValueError(f"Unknown bot family: {family!r}") from error
    return BOT_FAMILIES[resolved]


def supported_bot_families() -> tuple[str, ...]:
    return tuple(sorted(family.value for family in BOT_FAMILIES))
