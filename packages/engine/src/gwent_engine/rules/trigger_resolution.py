from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import GameEvent
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState
from gwent_engine.factions.passives import (
    resolve_after_round_winner_finalized,
    resolve_before_round_cleanup,
    resolve_round_outcome_modifiers,
    resolve_round_start_passives,
)
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.round_cleanup import (
    cleanup_battlefield,
    determine_match_winner,
    end_match,
    start_next_round,
)
from gwent_engine.rules.round_resolution import (
    apply_round_outcome,
    determine_round_outcome,
    is_round_effectively_over,
    next_round_starter,
)


def resolve_post_action_transitions(
    state: GameState,
    *,
    card_registry: CardRegistry | None,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if not _should_resolve_round(state):
        return state, ()
    if card_registry is None:
        raise IllegalActionError("Round resolution requires a card registry.")

    # Deterministic trigger order:
    # 1. round-outcome modifiers
    # 2. round result application
    # 3. cleanup modifiers
    # 4. battlefield cleanup
    # 5. post-round reward hooks
    # 6. match-end check or next-round initialization
    provisional_outcome = determine_round_outcome(
        state,
        card_registry,
        leader_registry=leader_registry,
    )
    modified_outcome, modifier_events = resolve_round_outcome_modifiers(state, provisional_outcome)
    state_after_modifiers = state_with_added_events(state, modifier_events)

    resolved_state, round_events = apply_round_outcome(state_after_modifiers, modified_outcome)
    retained_card_ids, cleanup_modifier_events = resolve_before_round_cleanup(
        resolved_state,
        card_registry=card_registry,
        rng=rng,
    )
    state_before_cleanup = state_with_added_events(resolved_state, cleanup_modifier_events)
    cleanup_state, cleanup_events = cleanup_battlefield(
        state_before_cleanup,
        card_registry=card_registry,
        retained_card_ids=retained_card_ids,
    )
    reward_state, reward_events = resolve_after_round_winner_finalized(
        cleanup_state,
        modified_outcome,
    )
    match_result = determine_match_winner(reward_state)
    if match_result is not False:
        ended_state, match_events = end_match(reward_state, winner=match_result)
        return (
            ended_state,
            modifier_events
            + round_events
            + cleanup_modifier_events
            + cleanup_events
            + reward_events
            + match_events,
        )

    next_state, round_start_events = start_next_round(
        reward_state,
        starting_player=next_round_starter(state, modified_outcome),
    )
    final_state, round_start_passive_events = resolve_round_start_passives(
        next_state,
        card_registry=card_registry,
        rng=rng,
    )
    return (
        final_state,
        modifier_events
        + round_events
        + cleanup_modifier_events
        + cleanup_events
        + reward_events
        + round_start_events
        + round_start_passive_events,
    )


def _should_resolve_round(state: GameState) -> bool:
    """
    Checks whether a round should trigger round resolution mechanism
    """
    return state.phase == state.phase.ROUND_RESOLUTION or (
        state.phase == state.phase.IN_ROUND and is_round_effectively_over(state)
    )


def state_with_added_events(state: GameState, events: tuple[GameEvent, ...]) -> GameState:
    if not events:
        return state
    return replace(state, event_counter=state.event_counter + len(events))
