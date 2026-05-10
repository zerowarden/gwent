from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.action_legality import is_legal_action
from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline import (
    BaseProfileDefinition,
    build_assessment,
    classify_context,
    compose_profile,
)
from gwent_engine.ai.baseline.projection import project_leader_action
from gwent_engine.ai.observations import (
    PlayerObservation,
    PublicPlayerStateView,
    build_player_observation,
)
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, SearchConfig
from gwent_engine.ai.search.candidate_generation import generate_search_candidates
from gwent_engine.ai.search.move_ordering import order_search_candidates
from gwent_engine.ai.search.public_info import redact_private_information
from gwent_engine.ai.search.types import (
    SearchReplyExplanation,
    SearchTraceFact,
    SearchValueTerm,
)
from gwent_engine.cards import CardRegistry
from gwent_engine.core import LeaderAbilityKind, Zone
from gwent_engine.core.actions import GameAction, PassAction, UseLeaderAbilityAction
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.players import opponent_player_id_from_state

PUBLIC_EXACT_LEADER_REPLY_KINDS = frozenset(
    {
        LeaderAbilityKind.CLEAR_WEATHER,
        LeaderAbilityKind.HORN_OWN_ROW,
        LeaderAbilityKind.SCORCH_OPPONENT_ROW,
        LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND,
        LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND,
        LeaderAbilityKind.OPTIMIZE_AGILE_ROWS,
        LeaderAbilityKind.SHUFFLE_ALL_DISCARDS_INTO_DECKS,
    }
)


@dataclass(frozen=True, slots=True)
class OpponentReplyCandidate:
    action: GameAction | None
    ordering_score: float
    reason: str
    inferred_penalty: float = 0.0
    explanation: SearchReplyExplanation | None = None


@dataclass(frozen=True, slots=True)
class HiddenReplyPressure:
    penalty: float
    components: tuple[SearchValueTerm, ...]
    notes: tuple[SearchTraceFact, ...] = ()


def generate_opponent_reply_candidates(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    profile_definition: BaseProfileDefinition,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[OpponentReplyCandidate, ...]:
    state = redact_private_information(
        state,
        viewer_player_id=viewer_player_id,
        card_registry=card_registry,
    )
    opponent_id = opponent_player_id_from_state(state, viewer_player_id)
    if state.pending_choice is not None and state.pending_choice.player_id == opponent_id:
        return _pending_choice_reply_candidates(
            state,
            viewer_player_id=viewer_player_id,
            opponent_id=opponent_id,
            profile_definition=profile_definition,
            config=config,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    candidates = list(
        _public_explicit_reply_candidates(
            state,
            opponent_id=opponent_id,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    )
    inferred_candidate = _inferred_hidden_reply_candidate(
        state,
        viewer_player_id=viewer_player_id,
        profile_definition=profile_definition,
        config=config,
        card_registry=card_registry,
        leader_registry=leader_registry,
        pending_choice=False,
    )
    if inferred_candidate is not None:
        candidates.append(inferred_candidate)
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.ordering_score,
            action_to_id(candidate.action) if candidate.action is not None else candidate.reason,
        ),
    )
    return tuple(ordered[: config.max_opponent_replies])


def _pending_choice_reply_candidates(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    opponent_id: PlayerId,
    profile_definition: BaseProfileDefinition,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> tuple[OpponentReplyCandidate, ...]:
    if _pending_choice_is_public_exact(state):
        return _public_exact_pending_choice_reply_candidates(
            state,
            opponent_id=opponent_id,
            config=config,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    inferred_pending_choice = _inferred_hidden_reply_candidate(
        state,
        viewer_player_id=viewer_player_id,
        profile_definition=profile_definition,
        config=config,
        card_registry=card_registry,
        leader_registry=leader_registry,
        pending_choice=True,
    )
    return () if inferred_pending_choice is None else (inferred_pending_choice,)


def _public_exact_pending_choice_reply_candidates(
    state: GameState,
    *,
    opponent_id: PlayerId,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> tuple[OpponentReplyCandidate, ...]:
    observation = build_player_observation(state, opponent_id, leader_registry)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=opponent_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=SeededRandom(0),
    )
    return tuple(
        OpponentReplyCandidate(
            action=candidate.action,
            ordering_score=candidate.ordering_score,
            reason=f"pending_choice:{candidate.reason}",
            explanation=SearchReplyExplanation(
                kind="exact_public",
                reason=f"pending_choice:{candidate.reason}",
            ),
        )
        for candidate in order_search_candidates(
            generate_search_candidates(
                observation,
                legal_actions,
                config=config,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
        )[: config.max_opponent_replies]
    )


def _public_explicit_reply_candidates(
    state: GameState,
    *,
    opponent_id: PlayerId,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> Iterable[OpponentReplyCandidate]:
    pass_action = PassAction(player_id=opponent_id)
    if is_legal_action(
        state,
        pass_action,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=SeededRandom(0),
    ):
        yield OpponentReplyCandidate(
            action=pass_action,
            ordering_score=0.0,
            reason="pass",
            explanation=SearchReplyExplanation(
                kind="exact_public",
                reason="pass",
            ),
        )

    if leader_registry is None:
        return
    observation = build_player_observation(state, opponent_id, leader_registry)
    opponent_public = _player_view(observation, opponent_id)
    leader_definition = leader_registry.get(opponent_public.leader.leader_id)
    if (
        opponent_public.leader.used
        or opponent_public.leader.disabled
        or leader_definition.ability_kind not in PUBLIC_EXACT_LEADER_REPLY_KINDS
    ):
        return
    action = UseLeaderAbilityAction(player_id=opponent_id)
    if not is_legal_action(
        state,
        action,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=SeededRandom(0),
    ):
        return
    projection = project_leader_action(
        action,
        observation=observation,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    ordering_score = 1.0
    if projection is not None:
        scoring = DEFAULT_BASELINE_CONFIG.candidate_scoring
        ordering_score = float(
            projection.projected_net_board_swing
            + projection.projected_hand_value_delta
            + (projection.viewer_hand_count_delta * scoring.leader_hand_delta_multiplier)
        )
    yield OpponentReplyCandidate(
        action=action,
        ordering_score=ordering_score,
        reason=f"leader:{leader_definition.ability_kind.value}",
        explanation=SearchReplyExplanation(
            kind="exact_public",
            reason=f"leader:{leader_definition.ability_kind.value}",
        ),
    )


def _inferred_hidden_reply_candidate(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    profile_definition: BaseProfileDefinition,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    pending_choice: bool,
) -> OpponentReplyCandidate | None:
    pressure = _estimated_hidden_pressure_penalty(
        state,
        viewer_player_id=viewer_player_id,
        profile_definition=profile_definition,
        config=config,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    if pressure is None:
        return None
    if not pending_choice:
        return _hidden_reply_candidate(
            reason="inferred_hidden_hand_pressure",
            penalty=pressure.penalty,
            components=pressure.components,
            notes=pressure.notes,
        )
    pending_choice_bonus = SearchValueTerm(
        name="hidden_pending_choice_bonus",
        value=config.hidden_pending_choice_bonus,
        formula="hidden_pending_choice_bonus",
        details=(
            SearchTraceFact(
                "hidden_pending_choice_bonus",
                f"{config.hidden_pending_choice_bonus:.2f}",
            ),
        ),
    )
    inferred_penalty = pressure.penalty + pending_choice_bonus.value
    return _hidden_reply_candidate(
        reason="inferred_hidden_pending_choice",
        penalty=inferred_penalty,
        components=(*pressure.components, pending_choice_bonus),
        notes=(
            *pressure.notes,
            SearchTraceFact("pending_choice_mode", "hidden_inferred"),
        ),
    )


def _hidden_reply_candidate(
    *,
    reason: str,
    penalty: float,
    components: tuple[SearchValueTerm, ...],
    notes: tuple[SearchTraceFact, ...],
) -> OpponentReplyCandidate:
    return OpponentReplyCandidate(
        action=None,
        ordering_score=penalty,
        reason=reason,
        inferred_penalty=penalty,
        explanation=SearchReplyExplanation(
            kind="inferred_hidden",
            reason=reason,
            value_adjustment=-penalty,
            components=components,
            notes=notes,
        ),
    )


def _estimated_hidden_pressure_penalty(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    profile_definition: BaseProfileDefinition,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> HiddenReplyPressure | None:
    observation = build_player_observation(state, viewer_player_id, leader_registry)
    assessment = build_assessment(observation, card_registry)
    if assessment.opponent.hand_count <= 0:
        return None
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=profile_definition,
    )
    tempo_per_card = (
        profile.elimination_estimated_opponent_tempo_per_card
        if assessment.is_elimination_round
        else profile.estimated_opponent_tempo_per_card
    )
    immediate_points = float(profile.weights.immediate_points)
    components: list[SearchValueTerm] = [
        SearchValueTerm(
            name="hidden_hand_tempo",
            value=float(assessment.opponent.hand_count * tempo_per_card) * immediate_points,
            formula="opponent_hand_count * tempo_per_card * immediate_points",
            details=(
                SearchTraceFact("opponent_hand_count", str(assessment.opponent.hand_count)),
                SearchTraceFact("tempo_per_card", f"{tempo_per_card:.2f}"),
                SearchTraceFact("immediate_points", f"{immediate_points:.2f}"),
            ),
        )
    ]
    if not assessment.opponent.leader_used:
        components.append(
            SearchValueTerm(
                name="unused_leader_bonus",
                value=config.hidden_reply_unused_leader_bonus * immediate_points,
                formula="hidden_reply_unused_leader_bonus * immediate_points",
                details=(
                    SearchTraceFact(
                        "hidden_reply_unused_leader_bonus",
                        f"{config.hidden_reply_unused_leader_bonus:.2f}",
                    ),
                    SearchTraceFact("immediate_points", f"{immediate_points:.2f}"),
                ),
            )
        )
    if assessment.opponent.hand_count >= assessment.viewer.hand_count:
        components.append(
            SearchValueTerm(
                name="hand_parity_bonus",
                value=config.hidden_reply_hand_parity_bonus * immediate_points,
                formula="hidden_reply_hand_parity_bonus * immediate_points",
                details=(
                    SearchTraceFact(
                        "hidden_reply_hand_parity_bonus",
                        f"{config.hidden_reply_hand_parity_bonus:.2f}",
                    ),
                    SearchTraceFact("viewer_hand_count", str(assessment.viewer.hand_count)),
                    SearchTraceFact("opponent_hand_count", str(assessment.opponent.hand_count)),
                    SearchTraceFact("immediate_points", f"{immediate_points:.2f}"),
                ),
            )
        )
    return HiddenReplyPressure(
        penalty=sum(component.value for component in components),
        components=tuple(components),
        notes=(
            SearchTraceFact("reply_mode", "inferred_hidden"),
            SearchTraceFact("context_mode", context.mode.value),
        ),
    )


def _player_view(
    observation: PlayerObservation,
    player_id: PlayerId,
) -> PublicPlayerStateView:
    players = observation.public_state.players
    return players[0] if players[0].player_id == player_id else players[1]


def _pending_choice_is_public_exact(state: GameState) -> bool:
    pending_choice = state.pending_choice
    if pending_choice is None:
        return False
    return all(
        state.card(card_id).zone in {Zone.BATTLEFIELD, Zone.DISCARD, Zone.WEATHER}
        for card_id in pending_choice.legal_target_card_instance_ids
    )
