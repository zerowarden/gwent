from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter

from gwent_engine.ai.action_ids import action_to_id, mulligan_selection_id
from gwent_engine.ai.actions import enumerate_legal_actions, enumerate_mulligan_selections
from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena.models import (
    FailedDecisionAttempt,
    MatchDecision,
    MatchDecisionKind,
    MatchExecution,
    MatchFailure,
    MatchFailureStage,
    MatchRecorder,
    MatchTransition,
    MulliganDecision,
    TerminationReason,
    TurnDecision,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.cards import CardRegistry, DeckDefinition
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.errors import GwentEngineError
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO, GameId, PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.reducer import apply_action_with_intermediate_state
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.game_setup import PlayerDeck, build_game_state
from gwent_engine.serialize import action_from_id


@dataclass(frozen=True, slots=True)
class _Decision:
    action: GameAction
    actor: PlayerId | None


class _MatchHaltError(Exception):
    """Internal control flow: stop the match and report a typed failure."""

    reason: TerminationReason
    failure: MatchFailure
    state: GameState

    def __init__(
        self,
        reason: TerminationReason,
        failure: MatchFailure,
        state: GameState,
    ) -> None:
        super().__init__(failure.message)
        self.reason = reason
        self.failure = failure
        self.state = state


def execute_match(
    *,
    game_id: GameId,
    player_one_bot: BotAgent,
    player_two_bot: BotAgent,
    player_one_deck: DeckDefinition,
    player_two_deck: DeckDefinition,
    starting_player: PlayerId,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
    action_budget: int,
    environment_seed: int | None = None,
    recorder: MatchRecorder | None = None,
) -> MatchExecution:
    """Run one authoritative bot match and report a typed outcome.

    `action_budget` counts accepted reducer transitions after the start-game
    action, so the joint mulligan action consumes exactly one slot. Engineering
    failures (setup, observation, enumeration, reducer, recording) and agent
    contract failures are classified rather than raised.
    """

    if action_budget <= 0:
        raise ValueError("action_budget must be positive.")

    try:
        initial_state = build_initial_state(
            game_id=game_id,
            player_one_deck=player_one_deck,
            player_two_deck=player_two_deck,
            environment_seed=environment_seed,
        )
    except Exception as error:
        return _failed_execution(
            game_id=game_id,
            state=None,
            reason=TerminationReason.ENGINE_ERROR,
            failure=_describe_failure(MatchFailureStage.START, None, error),
            environment_seed=environment_seed,
        )

    start_action = StartGameAction(starting_player=starting_player)
    try:
        state, start_events, start_intermediate = apply_action_with_intermediate_state(
            initial_state,
            start_action,
            rng=rng,
            leader_registry=leader_registry,
        )
    except Exception as error:
        return _failed_execution(
            game_id=game_id,
            state=initial_state,
            reason=TerminationReason.ENGINE_ERROR,
            failure=_describe_failure(MatchFailureStage.START, None, error),
            environment_seed=environment_seed,
        )

    bots = {
        initial_state.players[0].player_id: player_one_bot,
        initial_state.players[1].player_id: player_two_bot,
    }
    accepted_transitions = 0
    decision_count = 0
    pending_choice_occurred = state.pending_choice is not None

    def record_attempt(decision: MatchDecision) -> None:
        nonlocal decision_count
        decision_count += 1
        _record_decision(recorder, decision, state=state)

    try:
        _record_transition(
            recorder,
            MatchTransition(
                action=start_action,
                events=start_events,
                state_before=initial_state,
                state_after=state,
                intermediate_state=start_intermediate,
            ),
        )
        while True:
            if state.status == GameStatus.MATCH_ENDED:
                return MatchExecution(
                    game_id=game_id,
                    final_state=state,
                    termination=TerminationReason.COMPLETED,
                    accepted_transitions=accepted_transitions,
                    decision_count=decision_count,
                    pending_choice_occurred=pending_choice_occurred,
                    environment_seed=environment_seed,
                )
            if accepted_transitions >= action_budget:
                return MatchExecution(
                    game_id=game_id,
                    final_state=state,
                    termination=TerminationReason.ACTION_LIMIT,
                    accepted_transitions=accepted_transitions,
                    decision_count=decision_count,
                    pending_choice_occurred=pending_choice_occurred,
                    environment_seed=environment_seed,
                )

            decision = _choose_decision(
                state,
                bots=bots,
                card_registry=card_registry,
                leader_registry=leader_registry,
                rng=rng,
                record=record_attempt,
            )

            state_before = state
            try:
                state, events, intermediate_state = apply_action_with_intermediate_state(
                    state,
                    decision.action,
                    rng=rng,
                    card_registry=card_registry,
                    leader_registry=leader_registry,
                )
            except Exception as error:
                raise _MatchHaltError(
                    TerminationReason.ENGINE_ERROR,
                    _describe_failure(MatchFailureStage.REDUCE, decision.actor, error),
                    state_before,
                ) from error

            accepted_transitions += 1
            pending_choice_occurred = pending_choice_occurred or state.pending_choice is not None
            _record_transition(
                recorder,
                MatchTransition(
                    action=decision.action,
                    events=events,
                    state_before=state_before,
                    state_after=state,
                    intermediate_state=intermediate_state,
                ),
            )
    except _MatchHaltError as halt:
        return _failed_execution(
            game_id=game_id,
            state=halt.state,
            reason=halt.reason,
            failure=halt.failure,
            environment_seed=environment_seed,
            accepted_transitions=accepted_transitions,
            decision_count=decision_count,
            pending_choice_occurred=pending_choice_occurred,
        )


def build_initial_state(
    *,
    game_id: GameId,
    player_one_deck: DeckDefinition,
    player_two_deck: DeckDefinition,
    environment_seed: int | None,
) -> GameState:
    return build_game_state(
        game_id=game_id,
        player_decks=(
            PlayerDeck(player_id=PLAYER_ONE, deck=player_one_deck),
            PlayerDeck(player_id=PLAYER_TWO, deck=player_two_deck),
        ),
        rng_seed=environment_seed,
    )


def _choose_decision(
    state: GameState,
    *,
    bots: Mapping[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
    record: Callable[[MatchDecision], None],
) -> _Decision:
    if state.phase == Phase.MULLIGAN:
        selections = tuple(
            _choose_mulligan_decision(
                state,
                player_id=player.player_id,
                bots=bots,
                card_registry=card_registry,
                leader_registry=leader_registry,
                record=record,
            )
            for player in state.players
        )
        return _Decision(action=ResolveMulligansAction(selections=selections), actor=None)
    pending = state.pending_choice
    kind = MatchDecisionKind.PENDING_CHOICE if pending is not None else MatchDecisionKind.ACTION
    actor = pending.player_id if pending is not None else state.current_player
    if actor is None:
        raise _MatchHaltError(
            TerminationReason.ENGINE_ERROR,
            MatchFailure(
                _decision_failure_stage(kind),
                None,
                "EngineStateError",
                "In-round state has no current player.",
            ),
            state,
        )
    observation = _engine_call(
        MatchFailureStage.OBSERVE,
        actor,
        state,
        lambda: build_player_observation(state, actor, leader_registry),
    )
    actions = _engine_call(
        MatchFailureStage.ENUMERATE_ACTIONS,
        actor,
        state,
        lambda: enumerate_legal_actions(
            state,
            player_id=actor,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        ),
    )
    bot = bots[actor]
    choose = bot.choose_pending_choice if pending is not None else bot.choose_action
    action, duration = _agent_call(
        kind,
        actor,
        state,
        lambda: choose(
            observation, actions, card_registry=card_registry, leader_registry=leader_registry
        ),
        on_failure=lambda failure, elapsed: record(
            FailedDecisionAttempt(
                kind,
                actor,
                observation,
                tuple(action_to_id(a) for a in actions),
                None,
                elapsed,
                failure,
            )
        ),
    )
    if action not in actions:
        failure = MatchFailure(
            _decision_failure_stage(kind),
            actor,
            "IllegalActionError",
            f"{bot.display_name} emitted an illegal action: {_returned_diagnostic(action)}.",
        )
        record(
            FailedDecisionAttempt(
                kind,
                actor,
                observation,
                tuple(action_to_id(a) for a in actions),
                _returned_action_id(action),
                duration,
                failure,
            )
        )
        raise _MatchHaltError(TerminationReason.ILLEGAL_ACTION, failure, state)
    record(TurnDecision(kind, actor, observation, actions, action, duration))
    return _Decision(action=action, actor=actor)


def _choose_mulligan_decision(
    state: GameState,
    *,
    player_id: PlayerId,
    bots: Mapping[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    record: Callable[[MatchDecision], None],
) -> MulliganSelection:
    kind = MatchDecisionKind.MULLIGAN
    selections = _engine_call(
        MatchFailureStage.ENUMERATE_ACTIONS,
        player_id,
        state,
        lambda: enumerate_mulligan_selections(state, player_id),
    )
    observation = _engine_call(
        MatchFailureStage.OBSERVE,
        player_id,
        state,
        lambda: build_player_observation(state, player_id, leader_registry),
    )
    bot = bots[player_id]
    selection, duration = _agent_call(
        kind,
        player_id,
        state,
        lambda: bot.choose_mulligan(
            observation, selections, card_registry=card_registry, leader_registry=leader_registry
        ),
        on_failure=lambda failure, elapsed: record(
            FailedDecisionAttempt(
                kind,
                player_id,
                observation,
                tuple(mulligan_selection_id(s) for s in selections),
                None,
                elapsed,
                failure,
            )
        ),
    )
    if selection not in selections:
        failure = MatchFailure(
            _decision_failure_stage(kind),
            player_id,
            "IllegalActionError",
            f"{bot.display_name} emitted an illegal mulligan selection: "
            + f"{_returned_diagnostic(selection)}.",
        )
        chosen = _returned_mulligan_id(selection)
        record(
            FailedDecisionAttempt(
                kind,
                player_id,
                observation,
                tuple(mulligan_selection_id(s) for s in selections),
                chosen,
                duration,
                failure,
            )
        )
        raise _MatchHaltError(TerminationReason.ILLEGAL_ACTION, failure, state)
    record(MulliganDecision(player_id, observation, selections, selection, duration))
    return selection


def _returned_action_id(action: GameAction) -> str:
    return _canonical_returned_action_id(action) or _malformed_return_id(action)


def _canonical_returned_action_id(action: GameAction) -> str | None:
    try:
        identifier = action_to_id(action)
        decoded = action_from_id(identifier)
        if type(decoded) is type(action) and decoded == action:
            return identifier
    except Exception:
        # Malformed agent values must not turn diagnostic encoding into an engine error.
        pass
    return None


def _malformed_return_id(value: object) -> str:
    return f"malformed_return:{type(value).__module__}.{type(value).__qualname__}"


def _returned_diagnostic(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return _malformed_return_id(value)


def _engine_call[T](
    stage: MatchFailureStage,
    actor: PlayerId | None,
    state: GameState,
    operation: Callable[[], T],
) -> T:
    try:
        return operation()
    except Exception as error:
        raise _MatchHaltError(
            TerminationReason.ENGINE_ERROR,
            _describe_failure(stage, actor, error),
            state,
        ) from error


def _agent_call[T](
    kind: MatchDecisionKind,
    actor: PlayerId,
    state: GameState,
    operation: Callable[[], T],
    *,
    on_failure: Callable[[MatchFailure, float], None],
) -> tuple[T, float]:
    stage = _decision_failure_stage(kind)
    started = perf_counter()
    try:
        result = operation()
    except Exception as error:
        failure = _describe_failure(stage, actor, error)
        on_failure(failure, perf_counter() - started)
        reason = (
            TerminationReason.ENGINE_ERROR
            if isinstance(error, GwentEngineError)
            else TerminationReason.AGENT_ERROR
        )
        raise _MatchHaltError(reason, failure, state) from error
    return result, perf_counter() - started


def _decision_failure_stage(kind: MatchDecisionKind) -> MatchFailureStage:
    match kind:
        case MatchDecisionKind.MULLIGAN:
            return MatchFailureStage.CHOOSE_MULLIGAN
        case MatchDecisionKind.ACTION:
            return MatchFailureStage.CHOOSE_ACTION
        case MatchDecisionKind.PENDING_CHOICE:
            return MatchFailureStage.CHOOSE_PENDING_CHOICE


def _record_decision(
    recorder: MatchRecorder | None,
    decision: MatchDecision,
    *,
    state: GameState,
) -> None:
    if recorder is None:
        return
    try:
        recorder.record_decision(decision)
    except Exception as error:
        raise _MatchHaltError(
            TerminationReason.ENGINE_ERROR,
            _describe_failure(MatchFailureStage.RECORD, None, error),
            state,
        ) from error


def _record_transition(recorder: MatchRecorder | None, transition: MatchTransition) -> None:
    if recorder is None:
        return
    try:
        recorder.record_transition(transition)
    except Exception as error:
        raise _MatchHaltError(
            TerminationReason.ENGINE_ERROR,
            _describe_failure(MatchFailureStage.RECORD, None, error),
            transition.state_after,
        ) from error


def _describe_failure(
    stage: MatchFailureStage,
    actor: PlayerId | None,
    error: Exception,
) -> MatchFailure:
    return MatchFailure(
        stage=stage,
        actor=actor,
        exception_type=type(error).__name__,
        message=str(error),
    )


def _failed_execution(
    *,
    game_id: GameId,
    state: GameState | None,
    reason: TerminationReason,
    failure: MatchFailure,
    environment_seed: int | None,
    accepted_transitions: int = 0,
    decision_count: int = 0,
    pending_choice_occurred: bool = False,
) -> MatchExecution:
    return MatchExecution(
        game_id=game_id,
        final_state=state,
        termination=reason,
        accepted_transitions=accepted_transitions,
        decision_count=decision_count,
        pending_choice_occurred=pending_choice_occurred,
        environment_seed=environment_seed,
        failure=failure,
    )


def _returned_mulligan_id(selection: object) -> str:
    if isinstance(selection, MulliganSelection):
        action = ResolveMulligansAction(selections=(selection,))
        if _canonical_returned_action_id(action) is not None:
            return mulligan_selection_id(selection)
    return _malformed_return_id(selection)
