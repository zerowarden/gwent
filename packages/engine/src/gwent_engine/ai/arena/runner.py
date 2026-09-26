from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter

from gwent_engine.ai.actions import enumerate_legal_actions, enumerate_mulligan_selections
from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena.models import (
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


@dataclass(frozen=True, slots=True)
class _Decision:
    action: GameAction
    actor: PlayerId | None
    records: tuple[MatchDecision, ...]


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
            )
            decision_count += len(decision.records)
            for record in decision.records:
                _record_decision(recorder, record, state=state)

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
) -> _Decision:
    if state.phase == Phase.MULLIGAN:
        return _choose_mulligans(
            state,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    if state.pending_choice is not None:
        return _choose_pending_choice(
            state,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
    return _choose_turn(
        state,
        bots=bots,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def _choose_mulligans(
    state: GameState,
    *,
    bots: Mapping[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> _Decision:
    records = tuple(
        _choose_mulligan_decision(
            state,
            player_id=player.player_id,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        for player in state.players
    )
    return _Decision(
        action=ResolveMulligansAction(
            selections=tuple(record.selection for record in records),
        ),
        actor=None,
        records=records,
    )


def _choose_mulligan_decision(
    state: GameState,
    *,
    player_id: PlayerId,
    bots: Mapping[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> MulliganDecision:
    kind = MatchDecisionKind.MULLIGAN
    legal_selections = _engine_call(
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
    selection, duration_seconds = _agent_call(
        kind,
        player_id,
        state,
        lambda: bot.choose_mulligan(
            observation,
            legal_selections,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ),
    )
    if selection not in legal_selections:
        raise _MatchHaltError(
            TerminationReason.ILLEGAL_ACTION,
            MatchFailure(
                _decision_failure_stage(kind),
                player_id,
                "IllegalActionError",
                f"{bot.display_name} emitted an illegal mulligan selection.",
            ),
            state,
        )
    return MulliganDecision(
        actor=player_id,
        observation=observation,
        legal_selections=legal_selections,
        selection=selection,
        duration_seconds=duration_seconds,
    )


def _choose_pending_choice(
    state: GameState,
    *,
    bots: Mapping[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
) -> _Decision:
    kind = MatchDecisionKind.PENDING_CHOICE
    pending_choice = state.pending_choice
    assert pending_choice is not None
    player_id = pending_choice.player_id
    legal_actions = _engine_call(
        MatchFailureStage.ENUMERATE_ACTIONS,
        player_id,
        state,
        lambda: enumerate_legal_actions(
            state,
            player_id=player_id,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        ),
    )
    observation = _engine_call(
        MatchFailureStage.OBSERVE,
        player_id,
        state,
        lambda: build_player_observation(state, player_id, leader_registry),
    )
    bot = bots[player_id]
    action, duration_seconds = _agent_call(
        kind,
        player_id,
        state,
        lambda: bot.choose_pending_choice(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ),
    )
    if action not in legal_actions:
        raise _MatchHaltError(
            TerminationReason.ILLEGAL_ACTION,
            MatchFailure(
                _decision_failure_stage(kind),
                player_id,
                "IllegalActionError",
                f"{bot.display_name} emitted an illegal pending-choice action.",
            ),
            state,
        )
    return _Decision(
        action=action,
        actor=player_id,
        records=(
            TurnDecision(
                kind=kind,
                actor=player_id,
                observation=observation,
                legal_actions=legal_actions,
                action=action,
                duration_seconds=duration_seconds,
            ),
        ),
    )


def _choose_turn(
    state: GameState,
    *,
    bots: Mapping[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
) -> _Decision:
    kind = MatchDecisionKind.ACTION
    current_player = state.current_player
    if current_player is None:
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
    legal_actions = _engine_call(
        MatchFailureStage.ENUMERATE_ACTIONS,
        current_player,
        state,
        lambda: enumerate_legal_actions(
            state,
            player_id=current_player,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        ),
    )
    observation = _engine_call(
        MatchFailureStage.OBSERVE,
        current_player,
        state,
        lambda: build_player_observation(state, current_player, leader_registry),
    )
    bot = bots[current_player]
    action, duration_seconds = _agent_call(
        kind,
        current_player,
        state,
        lambda: bot.choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ),
    )
    if action not in legal_actions:
        raise _MatchHaltError(
            TerminationReason.ILLEGAL_ACTION,
            MatchFailure(
                _decision_failure_stage(kind),
                current_player,
                "IllegalActionError",
                f"{bot.display_name} emitted an illegal turn action.",
            ),
            state,
        )
    return _Decision(
        action=action,
        actor=current_player,
        records=(
            TurnDecision(
                kind=kind,
                actor=current_player,
                observation=observation,
                legal_actions=legal_actions,
                action=action,
                duration_seconds=duration_seconds,
            ),
        ),
    )


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
) -> tuple[T, float]:
    stage = _decision_failure_stage(kind)
    started = perf_counter()
    try:
        result = operation()
    except GwentEngineError as error:
        raise _MatchHaltError(
            TerminationReason.ENGINE_ERROR,
            _describe_failure(stage, actor, error),
            state,
        ) from error
    except Exception as error:
        raise _MatchHaltError(
            TerminationReason.AGENT_ERROR,
            _describe_failure(stage, actor, error),
            state,
        ) from error
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
