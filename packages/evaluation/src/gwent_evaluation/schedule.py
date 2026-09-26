from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO, GameId, PlayerId

from gwent_evaluation.models import AgentSpec, ScheduledMatch, SuiteSpec
from gwent_evaluation.provenance import canonical_hexdigest, derive_seed

CASE_ID_VERSION = 1
BLOCK_ID_VERSION = 1

_PLAYER_IDS = (PLAYER_ONE, PLAYER_TWO)


@dataclass(frozen=True, slots=True)
class ScheduleBlock:
    """One balanced block: a single opponent, deck pair, and declared root seed."""

    block_id: str
    opponent_agent: AgentSpec
    deck_pair: tuple[str, str]
    root_seed: int
    matches: tuple[ScheduledMatch, ...]


class SeedNamespace(StrEnum):
    ENVIRONMENT = "environment"
    CANDIDATE_POLICY = "candidate_policy"
    OPPONENT_POLICY = "opponent_policy"


class ScheduleError(ValueError):
    """Raised when a suite cannot be materialized into a unique balanced schedule."""


def other_seat(seat: PlayerId) -> PlayerId:
    if seat == PLAYER_ONE:
        return PLAYER_TWO
    if seat == PLAYER_TWO:
        return PLAYER_ONE
    raise ScheduleError(f"Unknown player seat: {seat!r}.")


def schedule_suite(suite: SuiteSpec) -> tuple[ScheduledMatch, ...]:
    """Materialize a suite into balanced, fully-resolved match legs.

    A block is `(opponent, deck pair, root seed)`; each block expands over
    candidate seat, requested starter, and deck assignment. The deck axis
    collapses when both deck ids are identical, so a block has 8 or 4 legs.
    """

    return tuple(match for block in schedule_blocks(suite) for match in block.matches)


def schedule_blocks(suite: SuiteSpec) -> tuple[ScheduleBlock, ...]:
    """Materialize a suite into balanced blocks of fully-resolved match legs."""

    blocks: list[ScheduleBlock] = []
    for opponent in suite.opponents:
        for deck_a, deck_b in suite.deck_pairs:
            for root_seed in suite.seeds:
                blocks.append(
                    _schedule_block(
                        suite=suite,
                        opponent=opponent,
                        deck_a=deck_a,
                        deck_b=deck_b,
                        root_seed=root_seed,
                    )
                )
    _reject_duplicate_case_ids([match for block in blocks for match in block.matches])
    return tuple(blocks)


def _schedule_block(
    *,
    suite: SuiteSpec,
    opponent: AgentSpec,
    deck_a: str,
    deck_b: str,
    root_seed: int,
) -> ScheduleBlock:
    return ScheduleBlock(
        block_id=canonical_hexdigest(
            {
                "version": BLOCK_ID_VERSION,
                "suite_id": suite.suite_id,
                "opponent": _agent_identity(opponent),
                "deck_pair": (deck_a, deck_b),
                "root_seed": root_seed,
            }
        ),
        opponent_agent=opponent,
        deck_pair=(deck_a, deck_b),
        root_seed=root_seed,
        matches=_block_legs(
            suite=suite,
            opponent=opponent,
            deck_a=deck_a,
            deck_b=deck_b,
            root_seed=root_seed,
        ),
    )


def _block_legs(
    *,
    suite: SuiteSpec,
    opponent: AgentSpec,
    deck_a: str,
    deck_b: str,
    root_seed: int,
) -> tuple[ScheduledMatch, ...]:
    deck_assignments = (
        ((deck_a, deck_b),) if deck_a == deck_b else ((deck_a, deck_b), (deck_b, deck_a))
    )
    return tuple(
        _scheduled_match(
            suite=suite,
            opponent=opponent,
            candidate_seat=candidate_seat,
            requested_starter=requested_starter,
            candidate_deck=deck_pair[0],
            opponent_deck=deck_pair[1],
            root_seed=root_seed,
        )
        for candidate_seat in _PLAYER_IDS
        for requested_starter in _PLAYER_IDS
        for deck_pair in deck_assignments
    )


def _scheduled_match(
    *,
    suite: SuiteSpec,
    opponent: AgentSpec,
    candidate_seat: PlayerId,
    requested_starter: PlayerId,
    candidate_deck: str,
    opponent_deck: str,
    root_seed: int,
) -> ScheduledMatch:
    case_id = canonical_hexdigest(
        {
            "version": CASE_ID_VERSION,
            "suite_id": suite.suite_id,
            "opponent": _agent_identity(opponent),
            "candidate_seat": str(candidate_seat),
            "requested_starting_player": str(requested_starter),
            "candidate_deck_id": candidate_deck,
            "opponent_deck_id": opponent_deck,
            "root_seed": root_seed,
            "action_budget": suite.action_budget,
        }
    )
    return ScheduledMatch(
        case_id=case_id,
        candidate_agent=suite.candidate,
        opponent_agent=opponent,
        candidate_seat=candidate_seat,
        requested_starting_player=requested_starter,
        candidate_deck_id=candidate_deck,
        opponent_deck_id=opponent_deck,
        environment_seed=derive_seed(
            namespace=SeedNamespace.ENVIRONMENT,
            identity=case_id,
            root_seed=root_seed,
        ),
        candidate_policy_seed=derive_seed(
            namespace=SeedNamespace.CANDIDATE_POLICY,
            identity=case_id,
            root_seed=root_seed,
        ),
        opponent_policy_seed=derive_seed(
            namespace=SeedNamespace.OPPONENT_POLICY,
            identity=case_id,
            root_seed=root_seed,
        ),
        game_id=GameId(f"eval_{case_id}"),
        action_budget=suite.action_budget,
    )


def _agent_identity(agent: AgentSpec) -> dict[str, object]:
    return {
        "agent_id": agent.agent_id,
        "family": agent.family.value,
        "profile": agent.profile,
    }


def _reject_duplicate_case_ids(matches: list[ScheduledMatch]) -> None:
    seen: set[str] = set()
    for match in matches:
        if match.case_id in seen:
            raise ScheduleError(f"Duplicate scheduled case id: {match.case_id!r}.")
        seen.add(match.case_id)
