from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.ai.baseline import DecisionAssessment, build_assessment
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.policy import SearchConfig
from gwent_engine.ai.search.public_info import redact_private_information
from gwent_engine.cards import CardRegistry
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.players import opponent_player_id_from_state


@dataclass(frozen=True, slots=True)
class ReplySearchDecision:
    enabled: bool
    reason: str


def should_search_opponent_reply(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> ReplySearchDecision:
    state = redact_private_information(
        state,
        viewer_player_id=viewer_player_id,
        card_registry=card_registry,
    )
    observation = build_player_observation(state, viewer_player_id, leader_registry)
    assessment = build_assessment(observation, card_registry)
    opponent_id = opponent_player_id_from_state(state, viewer_player_id)

    if state.status.value == "match_ended":
        decision = ReplySearchDecision(enabled=False, reason="match_ended")
    elif state.current_player != opponent_id:
        decision = ReplySearchDecision(enabled=False, reason="control_not_with_opponent")
    elif assessment.opponent_passed:
        decision = ReplySearchDecision(enabled=False, reason="opponent_already_passed")
    else:
        decision = _active_opponent_reply_decision(
            state,
            opponent_id=opponent_id,
            assessment=assessment,
            config=config,
        )
    return decision


def _active_opponent_reply_decision(
    state: GameState,
    *,
    opponent_id: PlayerId,
    assessment: DecisionAssessment,
    config: SearchConfig,
) -> ReplySearchDecision:
    opponent = assessment.opponent
    opponent_resources = opponent.hand_count + (0 if opponent.leader_used else 1)
    if opponent_resources <= 0:
        decision = ReplySearchDecision(enabled=False, reason="opponent_has_no_resources")
    elif state.pending_choice is not None and state.pending_choice.player_id == opponent_id:
        decision = ReplySearchDecision(enabled=True, reason="opponent_pending_choice")
    elif assessment.round_number >= 3:
        decision = ReplySearchDecision(enabled=True, reason="final_round")
    elif abs(assessment.score_gap) <= config.reply_search_score_gap_threshold:
        decision = ReplySearchDecision(enabled=True, reason="close_score_gap")
    elif opponent.hand_count >= config.reply_search_min_hand_count and (
        opponent.hand_count >= assessment.viewer.hand_count
    ):
        decision = ReplySearchDecision(enabled=True, reason="opponent_hidden_pressure")
    else:
        decision = ReplySearchDecision(enabled=False, reason="stable_position")
    return decision
