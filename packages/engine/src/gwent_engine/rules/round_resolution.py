from dataclasses import dataclass, replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core.events import GameEvent, RoundEndedEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.scoring import PlayerScore, calculate_round_scores


@dataclass(frozen=True, slots=True)
class RoundOutcome:
    scores: tuple[PlayerScore, PlayerScore]
    winner: PlayerId | None
    loser: PlayerId | None

    @property
    def is_draw(self) -> bool:
        return self.winner is None


def is_round_effectively_over(state: GameState) -> bool:
    return all(player.has_passed or not player.hand for player in state.players)


def determine_round_outcome(
    state: GameState,
    card_registry: CardRegistry,
    *,
    leader_registry: LeaderRegistry | None = None,
) -> RoundOutcome:
    first_score, second_score = calculate_round_scores(
        state,
        card_registry,
        leader_registry=leader_registry,
    )
    score_gap = first_score.total - second_score.total
    if score_gap == 0:
        return RoundOutcome(scores=(first_score, second_score), winner=None, loser=None)

    winning_score, losing_score = (
        (first_score, second_score) if score_gap > 0 else (second_score, first_score)
    )
    return RoundOutcome(
        scores=(first_score, second_score),
        winner=winning_score.player_id,
        loser=losing_score.player_id,
    )


def apply_round_outcome(
    state: GameState,
    outcome: RoundOutcome,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    first_player, second_player = state.players
    updated_players = (
        _apply_player_round_result(first_player, outcome),
        _apply_player_round_result(second_player, outcome),
    )
    first_score, second_score = outcome.scores
    round_ended_event = RoundEndedEvent(
        event_id=state.event_counter + 1,
        round_number=state.round_number,
        player_scores=(
            (first_score.player_id, first_score.total),
            (second_score.player_id, second_score.total),
        ),
        winner=outcome.winner,
    )
    next_state = replace(
        state,
        players=updated_players,
        event_counter=state.event_counter + 1,
    )
    return next_state, (round_ended_event,)


def next_round_starter(state: GameState, outcome: RoundOutcome) -> PlayerId:
    if outcome.winner is not None:
        return outcome.winner
    # The manual only specifies that the winner starts the next round.
    assert state.round_starter is not None
    return state.round_starter


def _apply_player_round_result(player: PlayerState, outcome: RoundOutcome) -> PlayerState:
    if outcome.is_draw:
        return replace(player, gems_remaining=player.gems_remaining - 1)
    if player.player_id == outcome.winner:
        return replace(player, round_wins=player.round_wins + 1)
    assert outcome.loser is not None
    if player.player_id == outcome.loser:
        return replace(player, gems_remaining=player.gems_remaining - 1)
    return player
