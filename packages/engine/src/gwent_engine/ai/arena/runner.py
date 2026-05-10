from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.ai.actions import enumerate_legal_actions, enumerate_mulligan_selections
from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.cards import CardRegistry, DeckDefinition
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.events import GameEvent, RoundEndedEvent
from gwent_engine.core.ids import CardInstanceId, GameId, PlayerId
from gwent_engine.core.randomness import SeededRandom, SupportsRandom
from gwent_engine.core.reducer import apply_action, apply_action_with_intermediate_state
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.game_setup import PlayerDeck, build_game_state
from gwent_engine.rules.scoring import battlefield_effective_strengths


@dataclass(frozen=True, slots=True)
class BotMatchStep:
    action: GameAction
    events: tuple[GameEvent, ...]
    state_before: GameState
    state_after: GameState
    round_summary_state: GameState | None
    effective_strengths_before: Mapping[CardInstanceId, int]
    effective_strengths_after: Mapping[CardInstanceId, int]
    round_summary_strengths: Mapping[CardInstanceId, int]


@dataclass(frozen=True, slots=True)
class BotMatchRun:
    game_id: GameId
    player_one_id: PlayerId
    player_two_id: PlayerId
    player_one_deck_id: str
    player_two_deck_id: str
    player_one_bot_name: str
    player_two_bot_name: str
    rng_name: str
    steps: tuple[BotMatchStep, ...]
    pending_choice_state: GameState | None
    final_state: GameState


def run_bot_match(
    *,
    game_id: GameId,
    player_one_bot: BotAgent,
    player_two_bot: BotAgent,
    player_one_deck: DeckDefinition,
    player_two_deck: DeckDefinition,
    starting_player: PlayerId,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom | None = None,
    max_steps: int = 512,
) -> BotMatchRun:
    match_rng = rng or SeededRandom(0)
    state = build_game_state(
        game_id=game_id,
        player_decks=(
            PlayerDeck(player_id=PlayerId("p1"), deck=player_one_deck),
            PlayerDeck(player_id=PlayerId("p2"), deck=player_two_deck),
        ),
        rng_seed=0,
    )
    initial_state = state
    start_action = StartGameAction(starting_player=starting_player)
    state, start_events = apply_action(
        state,
        start_action,
        rng=match_rng,
        leader_registry=leader_registry,
    )
    steps: list[BotMatchStep] = [
        _build_match_step(
            action=start_action,
            events=start_events,
            state_before=initial_state,
            state_after=state,
            round_summary_state=None,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    ]
    pending_choice_state: GameState | None = state if state.pending_choice is not None else None
    bots = {
        state.players[0].player_id: player_one_bot,
        state.players[1].player_id: player_two_bot,
    }

    for _ in range(max_steps):
        if state.status == GameStatus.MATCH_ENDED:
            return _build_match_run(
                state=state,
                game_id=game_id,
                player_one_deck=player_one_deck,
                player_two_deck=player_two_deck,
                player_one_bot=player_one_bot,
                player_two_bot=player_two_bot,
                rng=match_rng,
                steps=steps,
                pending_choice_state=pending_choice_state,
            )
        action = _choose_next_action(
            state,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=match_rng,
        )
        state_before = state
        state, action_events, intermediate_state = apply_action_with_intermediate_state(
            state,
            action,
            rng=match_rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        round_summary_state = (
            intermediate_state
            if any(isinstance(event, RoundEndedEvent) for event in action_events)
            else None
        )
        steps.append(
            _build_match_step(
                action=action,
                events=action_events,
                state_before=state_before,
                state_after=state,
                round_summary_state=round_summary_state,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
        )
        if pending_choice_state is None and state.pending_choice is not None:
            pending_choice_state = state
    raise RuntimeError(f"Bot match did not finish within {max_steps} actions.")


def _choose_next_action(
    state: GameState,
    *,
    bots: dict[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
) -> GameAction:
    if state.phase == Phase.MULLIGAN:
        return _choose_mulligan_action(
            state,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    if state.pending_choice is not None:
        return _choose_pending_choice_action(
            state,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
    return _choose_turn_action(
        state,
        bots=bots,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def _choose_mulligan_action(
    state: GameState,
    *,
    bots: dict[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> ResolveMulligansAction:
    selections = tuple(
        _choose_player_mulligan_selection(
            state,
            player_id=player.player_id,
            bots=bots,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        for player in state.players
    )
    return ResolveMulligansAction(selections=selections)


def _choose_player_mulligan_selection(
    state: GameState,
    *,
    player_id: PlayerId,
    bots: dict[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> MulliganSelection:
    legal_selections = enumerate_mulligan_selections(state, player_id)
    observation = build_player_observation(state, player_id, leader_registry)
    selection = bots[player_id].choose_mulligan(
        observation,
        legal_selections,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    if selection not in legal_selections:
        raise RuntimeError(f"{bots[player_id].display_name} emitted illegal mulligan.")
    return selection


def _choose_pending_choice_action(
    state: GameState,
    *,
    bots: dict[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
) -> GameAction:
    pending_choice = state.pending_choice
    assert pending_choice is not None
    player_id: PlayerId = pending_choice.player_id
    legal_actions = enumerate_legal_actions(
        state,
        player_id=player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )
    observation = build_player_observation(state, player_id, leader_registry)
    action = bots[player_id].choose_pending_choice(
        observation,
        legal_actions,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    if action not in legal_actions:
        raise RuntimeError(f"{bots[player_id].display_name} emitted illegal pending-choice action.")
    return action


def _choose_turn_action(
    state: GameState,
    *,
    bots: dict[PlayerId, BotAgent],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom,
) -> GameAction:
    current_player = state.current_player
    if current_player is None:
        raise RuntimeError("In-round state has no current_player.")
    legal_actions = enumerate_legal_actions(
        state,
        player_id=current_player,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )
    observation = build_player_observation(state, current_player, leader_registry)
    current_bot = bots[current_player]
    action = current_bot.choose_action(
        observation,
        legal_actions,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    if action not in legal_actions:
        raise RuntimeError(f"{current_bot.display_name} emitted illegal turn action.")
    return action


def _build_match_step(
    *,
    action: GameAction,
    events: tuple[GameEvent, ...],
    state_before: GameState,
    state_after: GameState,
    round_summary_state: GameState | None,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> BotMatchStep:
    return BotMatchStep(
        action=action,
        events=events,
        state_before=state_before,
        state_after=state_after,
        round_summary_state=round_summary_state,
        effective_strengths_before=battlefield_effective_strengths(
            state_before,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ),
        effective_strengths_after=battlefield_effective_strengths(
            state_after,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ),
        round_summary_strengths=(
            battlefield_effective_strengths(
                round_summary_state,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
            if round_summary_state is not None
            else {}
        ),
    )


def _build_match_run(
    *,
    state: GameState,
    game_id: GameId,
    player_one_deck: DeckDefinition,
    player_two_deck: DeckDefinition,
    player_one_bot: BotAgent,
    player_two_bot: BotAgent,
    rng: SupportsRandom,
    steps: list[BotMatchStep],
    pending_choice_state: GameState | None,
) -> BotMatchRun:
    return BotMatchRun(
        game_id=game_id,
        player_one_id=state.players[0].player_id,
        player_two_id=state.players[1].player_id,
        player_one_deck_id=str(player_one_deck.deck_id),
        player_two_deck_id=str(player_two_deck.deck_id),
        player_one_bot_name=player_one_bot.display_name,
        player_two_bot_name=player_two_bot.display_name,
        rng_name=type(rng).__name__,
        steps=tuple(steps),
        pending_choice_state=pending_choice_state,
        final_state=state,
    )
