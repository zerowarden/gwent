from __future__ import annotations

import pytest
from gwent_evaluation.agents import resolve_agent
from gwent_evaluation.models import BotFamily

from tests.evaluation.support import agent_spec


def test_resolve_agent_resolves_omitted_profile_to_canonical_default() -> None:
    agent = resolve_agent(agent_spec(family=BotFamily.HEURISTIC))

    assert agent.family_id == "heuristic"
    assert agent.profile_id == "neutral"


def test_agent_digest_is_stable_and_profile_sensitive() -> None:
    neutral = resolve_agent(agent_spec(family=BotFamily.HEURISTIC))
    other_neutral = resolve_agent(agent_spec(family=BotFamily.HEURISTIC))
    conservative = resolve_agent(agent_spec(family=BotFamily.HEURISTIC, profile="conservative"))

    assert neutral.digest() == other_neutral.digest()
    assert neutral.digest() != conservative.digest()


def test_agent_digest_ignores_human_labels() -> None:
    first = resolve_agent(agent_spec(agent_id="first", family=BotFamily.HEURISTIC))
    second = resolve_agent(agent_spec(agent_id="second", family=BotFamily.HEURISTIC))

    assert first.digest() == second.digest()


def test_agent_digest_distinguishes_families() -> None:
    random_agent = resolve_agent(agent_spec(family=BotFamily.RANDOM))
    greedy_agent = resolve_agent(agent_spec(family=BotFamily.GREEDY))
    heuristic_agent = resolve_agent(agent_spec(family=BotFamily.HEURISTIC))
    search_agent = resolve_agent(agent_spec(family=BotFamily.SEARCH))

    digests = {
        random_agent.digest(),
        greedy_agent.digest(),
        heuristic_agent.digest(),
        search_agent.digest(),
    }
    assert len(digests) == 4


@pytest.mark.parametrize("family", [BotFamily.RANDOM, BotFamily.GREEDY])
def test_resolve_agent_rejects_profile_for_profileless_family(family: BotFamily) -> None:
    with pytest.raises(ValueError, match="does not support a profile"):
        _ = resolve_agent(agent_spec(family=family, profile="neutral"))


def test_resolve_agent_rejects_unrecognized_profile() -> None:
    with pytest.raises(ValueError, match="not a recognized profile"):
        _ = resolve_agent(agent_spec(family=BotFamily.HEURISTIC, profile="mystery"))


@pytest.mark.parametrize("family", [BotFamily.HEURISTIC, BotFamily.SEARCH])
def test_build_uses_the_resolved_trial_profile(family: BotFamily) -> None:
    from dataclasses import replace

    resolved = resolve_agent(agent_spec(family=family))
    assert resolved.profile is not None
    trial = replace(
        resolved.profile,
        profile_id="unnamed-trial",
        weights=replace(resolved.profile.weights, immediate_points=123.0),
    )
    candidate = replace(resolved, profile=trial)
    assert candidate.digest() != resolved.digest()
    # An unregistered profile cannot be looked up by name. Both constructors
    # must accept the exact resolved object that contributed to the digest.
    bot = candidate.build(bot_id="trial")
    assert "unnamed-trial" in bot.display_name
