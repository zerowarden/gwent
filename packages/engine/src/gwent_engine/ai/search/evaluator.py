from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.ai.baseline import (
    BaseProfileDefinition,
    DecisionAssessment,
    build_assessment,
    classify_context,
    compose_profile,
)
from gwent_engine.ai.baseline.projection import projected_future_card_value
from gwent_engine.ai.observations import PlayerObservation, build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, SearchConfig
from gwent_engine.ai.search.public_info import redact_private_information
from gwent_engine.ai.search.types import SearchTraceFact, SearchValueTerm
from gwent_engine.cards import CardRegistry
from gwent_engine.core import AbilityKind, CardType, GameStatus
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry


@dataclass(frozen=True, slots=True)
class SearchStateEvaluation:
    value: float
    facts: tuple[SearchTraceFact, ...]
    terms: tuple[SearchValueTerm, ...]
    notes: tuple[str, ...]


def evaluate_search_state(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    profile_definition: BaseProfileDefinition,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> SearchStateEvaluation:
    state = redact_private_information(
        state,
        viewer_player_id=viewer_player_id,
        card_registry=card_registry,
    )
    observation = build_player_observation(state, viewer_player_id, leader_registry)
    assessment = build_assessment(observation, card_registry)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=profile_definition,
    )

    if state.status == GameStatus.MATCH_ENDED:
        return _terminal_match_evaluation(
            state,
            viewer_player_id=viewer_player_id,
            config=config,
        )

    round_wins_delta = assessment.viewer.round_wins - assessment.opponent.round_wins
    leader_delta = (0 if assessment.viewer.leader_used else 1) - (
        0 if assessment.opponent.leader_used else 1
    )
    effective_hand_value = _effective_viewer_hand_value_for_search(assessment)
    draw_followup_value = _known_reachable_draw_followup_value(
        observation,
        assessment=assessment,
        card_registry=card_registry,
        config=config,
    )
    terms = [
        SearchValueTerm(
            name="round_wins_delta",
            value=round_wins_delta * config.round_win_value,
            formula="round_wins_delta * round_win_value",
            details=(
                SearchTraceFact("round_wins_delta", str(round_wins_delta)),
                SearchTraceFact("round_win_value", f"{config.round_win_value:.2f}"),
            ),
        ),
        SearchValueTerm(
            name="score_gap",
            value=(
                profile.weights.immediate_points * config.score_gap_scale * assessment.score_gap
            ),
            formula="immediate_points * score_gap_scale * score_gap",
            details=(
                SearchTraceFact("immediate_points", f"{profile.weights.immediate_points:.2f}"),
                SearchTraceFact("score_gap_scale", f"{config.score_gap_scale:.2f}"),
                SearchTraceFact("score_gap", str(assessment.score_gap)),
            ),
        ),
        SearchValueTerm(
            name="card_advantage",
            value=(
                profile.weights.card_advantage
                * config.card_advantage_scale
                * assessment.card_advantage
            ),
            formula="card_advantage_weight * card_advantage_scale * card_advantage",
            details=(
                SearchTraceFact("card_advantage_weight", f"{profile.weights.card_advantage:.2f}"),
                SearchTraceFact("card_advantage_scale", f"{config.card_advantage_scale:.2f}"),
                SearchTraceFact("card_advantage", str(assessment.card_advantage)),
            ),
        ),
        SearchValueTerm(
            name="effective_hand_value",
            value=(
                profile.weights.remaining_hand_value
                * config.hand_value_scale
                * effective_hand_value
            ),
            formula="remaining_hand_value * hand_value_scale * effective_hand_value",
            details=(
                SearchTraceFact(
                    "remaining_hand_value",
                    f"{profile.weights.remaining_hand_value:.2f}",
                ),
                SearchTraceFact("hand_value_scale", f"{config.hand_value_scale:.2f}"),
                SearchTraceFact("viewer_hand_value", str(assessment.viewer.hand_value)),
                SearchTraceFact("effective_hand_value", str(effective_hand_value)),
            ),
        ),
        SearchValueTerm(
            name="draw_followup_value",
            value=draw_followup_value * config.draw_followup_scale,
            formula="draw_followup_value * draw_followup_scale",
            details=(
                SearchTraceFact("draw_followup_value", f"{draw_followup_value:.2f}"),
                SearchTraceFact("draw_followup_scale", f"{config.draw_followup_scale:.2f}"),
            ),
        ),
        SearchValueTerm(
            name="leader_delta",
            value=profile.weights.leader_value * config.leader_delta_scale * leader_delta,
            formula="leader_value * leader_delta_scale * leader_delta",
            details=(
                SearchTraceFact("leader_value", f"{profile.weights.leader_value:.2f}"),
                SearchTraceFact("leader_delta_scale", f"{config.leader_delta_scale:.2f}"),
                SearchTraceFact("leader_delta", str(leader_delta)),
            ),
        ),
    ]
    if assessment.opponent_passed and assessment.score_gap > 0:
        terms.append(
            SearchValueTerm(
                name="exact_finish_bonus",
                value=(profile.weights.exact_finish_bonus * config.exact_finish_bonus_scale),
                formula="exact_finish_bonus * exact_finish_bonus_scale",
                details=(
                    SearchTraceFact(
                        "exact_finish_bonus",
                        f"{profile.weights.exact_finish_bonus:.2f}",
                    ),
                    SearchTraceFact(
                        "exact_finish_bonus_scale",
                        f"{config.exact_finish_bonus_scale:.2f}",
                    ),
                ),
            )
        )
    value = sum(term.value for term in terms)
    return SearchStateEvaluation(
        value=value,
        facts=(
            SearchTraceFact("leaf", "state_eval"),
            SearchTraceFact("context_mode", context.mode.value),
            SearchTraceFact("score_gap", str(assessment.score_gap)),
            SearchTraceFact("card_advantage", str(assessment.card_advantage)),
        ),
        terms=tuple(terms),
        notes=(
            "leaf=state_eval",
            f"round_wins_delta={round_wins_delta}",
            f"score_gap={assessment.score_gap}",
            f"card_advantage={assessment.card_advantage}",
            f"viewer_hand_value={assessment.viewer.hand_value}",
            f"effective_hand_value={effective_hand_value}",
            f"draw_followup_value={draw_followup_value:.2f}",
            f"leader_delta={leader_delta}",
            f"context_mode={context.mode}",
        ),
    )


def _terminal_match_evaluation(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    config: SearchConfig,
) -> SearchStateEvaluation:
    winner_label = _terminal_winner_label(state, viewer_player_id=viewer_player_id)
    return SearchStateEvaluation(
        value=_terminal_match_value(winner_label, config=config),
        facts=(
            SearchTraceFact("leaf", "match_end"),
            SearchTraceFact("winner", winner_label),
        ),
        terms=(),
        notes=("leaf=match_end", f"winner={winner_label}"),
    )


def _terminal_winner_label(state: GameState, *, viewer_player_id: PlayerId) -> str:
    if state.match_winner == viewer_player_id:
        return "viewer"
    if state.match_winner is None:
        return "draw"
    return "opponent"


def _terminal_match_value(winner_label: str, *, config: SearchConfig) -> float:
    if winner_label == "viewer":
        return config.terminal_match_value
    if winner_label == "draw":
        return 0.0
    return -config.terminal_match_value


def _effective_viewer_hand_value_for_search(assessment: DecisionAssessment) -> int:
    """Return the hand value term that should survive into the search leaf.

    Search phase 2/3 stops after the viewer turn plus an optional opponent
    reply. That makes the leaf especially vulnerable to overvaluing "safe"
    passes in final or elimination rounds: once the viewer has passed, those
    held cards are no longer future-round resources, they are dead.

    We therefore keep ordinary hand preservation in non-elimination rounds, but
    zero it once the viewer has already passed in an elimination state. This is
    the round-3 failure mode from the match review: search preferred pass
    because it still credited dead post-pass hand value.
    """

    if assessment.viewer.passed and assessment.is_elimination_round:
        return 0
    return assessment.viewer.hand_value


def _known_reachable_draw_followup_value(
    observation: PlayerObservation,
    *,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    config: SearchConfig,
) -> float:
    """Value known draw engines that remain live beyond the shallow horizon.

    This exists for states like:
    - round 3
    - viewer is narrowly ahead
    - an opponent spy is sitting on the viewer board
    - viewer can Decoy that spy back, then replay it next turn and draw

    A plain 1-ply-plus-reply leaf sees the temporary tempo loss from Decoy, but
    not the next viewer turn where the reclaimed spy converts deck contents into
    cards. Without an explicit continuation term, search incorrectly prefers
    passing or body-only plays.

    The helper is deliberately state-based rather than action-based:
    - it only uses the viewer's exact known hand/discard/deck information
    - it only counts draw lines that are immediately reachable from the current
      leaf state
    - it returns zero once the viewer has passed, because those follow-ups are
      no longer available
    """

    if assessment.viewer.passed:
        return 0.0
    deck_count = len(observation.viewer_deck)
    if deck_count <= 0:
        return 0.0
    reachable_draws = min(
        deck_count,
        _reachable_known_draw_count(
            observation,
            assessment=assessment,
            card_registry=card_registry,
        ),
    )
    if reachable_draws <= 0:
        return 0.0
    return float(reachable_draws) * _optimistic_known_draw_value(
        observation,
        card_registry=card_registry,
        config=config,
    )


def _reachable_known_draw_count(
    observation: PlayerObservation,
    *,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
) -> int:
    total = 0
    viewer_rows = next(
        player.rows
        for player in observation.public_state.players
        if player.player_id == observation.viewer_player_id
    )
    viewer_board = (
        *viewer_rows.close,
        *viewer_rows.ranged,
        *viewer_rows.siege,
    )
    viewer_discard_has_spy = any(
        AbilityKind.SPY in definition.ability_kinds
        for definition in assessment.viewer.discard_definitions
    )
    viewer_board_has_reclaimable_spy = any(
        (AbilityKind.SPY in definition.ability_kinds and not definition.is_hero)
        for definition in (card_registry.get(card.definition_id) for card in viewer_board)
    )
    for card in observation.viewer_hand:
        definition = card_registry.get(card.definition_id)
        if AbilityKind.SPY in definition.ability_kinds:
            total += 2
            continue
        if AbilityKind.MEDIC in definition.ability_kinds and viewer_discard_has_spy:
            total += 2
            continue
        if (
            definition.card_type == CardType.SPECIAL
            and AbilityKind.DECOY in definition.ability_kinds
            and viewer_board_has_reclaimable_spy
        ):
            total += 2
    return total


def _optimistic_known_draw_value(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    config: SearchConfig,
) -> float:
    candidate_values = sorted(
        (
            projected_future_card_value(
                card_registry.get(card.definition_id),
                observation=observation,
                card_registry=card_registry,
            )
            for card in observation.viewer_deck
        ),
        reverse=True,
    )
    if not candidate_values:
        return config.optimistic_known_draw_floor
    strongest = candidate_values[
        : min(config.optimistic_known_draw_top_count, len(candidate_values))
    ]
    return max(config.optimistic_known_draw_floor, sum(strongest) / len(strongest))
