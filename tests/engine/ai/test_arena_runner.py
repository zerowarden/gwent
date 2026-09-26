from __future__ import annotations

from dataclasses import replace

import pytest
from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena import (
    MatchExecution,
    MatchFailureStage,
    TerminationReason,
    create_bot,
    execute_match,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import DeckDefinition
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.errors import GwentEngineError
from gwent_engine.core.ids import GameId, LeaderId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.decks import load_sample_decks

from tests.engine.ai.bots import (
    CountingBot,
    FailingBot,
    IllegalActionBot,
    LeaderChoiceBot,
)
from tests.engine.support import (
    CARD_REGISTRY,
    DATA_DIR,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
)

_STARTING_DECK_IDS = ("monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict")
_DESTROYER_LEADER_ID = LeaderId("monsters_eredin_destroyer_of_worlds")


def _sample_decks() -> dict[str, DeckDefinition]:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    return {str(deck.deck_id): deck for deck in decks}


def _execute(
    *,
    player_one_bot: BotAgent | None = None,
    player_two_bot: BotAgent | None = None,
    player_one_deck: DeckDefinition | None = None,
    player_two_deck: DeckDefinition | None = None,
    action_budget: int = 512,
    seed: int = 7,
) -> MatchExecution:
    decks = _sample_decks()
    return execute_match(
        game_id=GameId("arena_runner_test"),
        player_one_bot=player_one_bot or create_bot("heuristic", bot_id="p1_bot"),
        player_two_bot=player_two_bot or create_bot("greedy", bot_id="p2_bot"),
        player_one_deck=player_one_deck or decks[_STARTING_DECK_IDS[0]],
        player_two_deck=player_two_deck or decks[_STARTING_DECK_IDS[1]],
        starting_player=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        rng=SeededRandom(seed),
        action_budget=action_budget,
        environment_seed=seed,
    )


def _leader_deck() -> DeckDefinition:
    return replace(
        _sample_decks()["monsters_muster_swarm_strict"],
        leader_id=_DESTROYER_LEADER_ID,
    )


def test_execute_match_completes_seeded_match() -> None:
    result = _execute()

    assert result.termination is TerminationReason.COMPLETED
    assert result.completed is True
    assert result.failure is None
    assert result.final_state is not None
    assert result.final_state.status is GameStatus.MATCH_ENDED
    assert result.match_winner == result.final_state.match_winner
    assert result.accepted_transitions > 0
    assert result.environment_seed == 7


def test_start_action_is_not_budgeted_and_mulligans_are_one_transition() -> None:
    result = _execute(action_budget=1)

    assert result.termination is TerminationReason.ACTION_LIMIT
    assert result.completed is False
    assert result.match_winner is None
    assert result.failure is None
    assert result.accepted_transitions == 1
    assert result.decision_count == 2
    assert result.final_state is not None
    assert result.final_state.phase is Phase.IN_ROUND


def test_mulligan_phase_calls_each_bot_once() -> None:
    player_one = CountingBot(delegate=create_bot("greedy", bot_id="p1_bot"))
    player_two = CountingBot(delegate=create_bot("greedy", bot_id="p2_bot"))

    result = _execute(
        player_one_bot=player_one,
        player_two_bot=player_two,
        action_budget=1,
    )

    assert result.decision_count == 2
    assert player_one.mulligan_calls == 1
    assert player_two.mulligan_calls == 1
    assert player_one.action_calls == 0
    assert player_two.action_calls == 0


def test_pending_choice_routes_to_its_owner() -> None:
    player_one = CountingBot(
        delegate=LeaderChoiceBot(delegate=create_bot("greedy", bot_id="p1_inner"))
    )
    player_two = CountingBot(delegate=create_bot("greedy", bot_id="p2_inner"))

    result = _execute(
        player_one_bot=player_one,
        player_two_bot=player_two,
        player_one_deck=_leader_deck(),
        action_budget=3,
    )

    assert result.pending_choice_occurred is True
    assert result.decision_count == 4
    assert player_one.action_calls == 1
    assert player_one.pending_choice_calls == 1
    assert player_two.action_calls == 0
    assert player_two.pending_choice_calls == 0


def test_illegal_action_is_classified() -> None:
    result = _execute(
        player_one_bot=IllegalActionBot(delegate=create_bot("greedy", bot_id="p1_inner")),
        action_budget=8,
    )

    assert result.termination is TerminationReason.ILLEGAL_ACTION
    assert result.completed is False
    assert result.failure is not None
    assert result.failure.stage is MatchFailureStage.CHOOSE_ACTION
    assert result.failure.actor == PLAYER_ONE_ID
    assert result.failure.exception_type == "IllegalActionError"


def test_agent_exception_is_classified() -> None:
    result = _execute(
        player_one_bot=FailingBot(
            delegate=create_bot("greedy", bot_id="p1_inner"),
            error=RuntimeError("fixture failure"),
        ),
        action_budget=8,
    )

    assert result.termination is TerminationReason.AGENT_ERROR
    assert result.failure is not None
    assert result.failure.stage is MatchFailureStage.CHOOSE_ACTION
    assert result.failure.actor == PLAYER_ONE_ID
    assert result.failure.exception_type == "RuntimeError"
    assert result.failure.message == "fixture failure"


def test_engine_exception_from_agent_is_classified_as_engine_error() -> None:
    result = _execute(
        player_one_bot=FailingBot(
            delegate=create_bot("greedy", bot_id="p1_inner"),
            error=GwentEngineError("materialization failed"),
        ),
        action_budget=8,
    )

    assert result.termination is TerminationReason.ENGINE_ERROR
    assert result.failure is not None
    assert result.failure.stage is MatchFailureStage.CHOOSE_ACTION
    assert result.failure.exception_type == "GwentEngineError"


def test_reducer_exception_is_classified_as_engine_error() -> None:
    result = _execute(
        player_one_bot=LeaderChoiceBot(
            delegate=create_bot("greedy", bot_id="p1_inner"),
            valid_split=False,
        ),
        player_one_deck=_leader_deck(),
        action_budget=3,
    )

    assert result.termination is TerminationReason.ENGINE_ERROR
    assert result.failure is not None
    assert result.failure.stage is MatchFailureStage.REDUCE
    assert result.failure.exception_type == "IllegalActionError"


def test_observation_exception_is_classified_as_engine_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_observation(*args: object, **kwargs: object) -> PlayerObservation:
        del args, kwargs
        raise GwentEngineError("observation failed")

    monkeypatch.setattr(
        "gwent_engine.ai.arena.runner.build_player_observation",
        fail_observation,
    )

    result = _execute(action_budget=8)

    assert result.termination is TerminationReason.ENGINE_ERROR
    assert result.failure is not None
    assert result.failure.stage is MatchFailureStage.OBSERVE


def test_terminal_transition_on_final_budget_slot_is_completed() -> None:
    full = _execute()
    assert full.termination is TerminationReason.COMPLETED
    assert full.accepted_transitions > 1

    exact = _execute(action_budget=full.accepted_transitions)
    assert exact.termination is TerminationReason.COMPLETED
    assert exact.accepted_transitions == full.accepted_transitions

    short = _execute(action_budget=full.accepted_transitions - 1)
    assert short.termination is TerminationReason.ACTION_LIMIT
