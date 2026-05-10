from __future__ import annotations

from collections import Counter

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.mulligan_scoring import mulligan_selection_score
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_MULLIGAN_POLICY
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import MulliganSelection


def choose_mulligan_selection(
    observation: PlayerObservation,
    legal_selections: tuple[MulliganSelection, ...],
    *,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
) -> MulliganSelection:
    if not legal_selections:
        raise ValueError("choose_mulligan_selection requires at least one legal selection.")
    hand_by_id = {
        card.instance_id: card_registry.get(card.definition_id) for card in observation.viewer_hand
    }
    definition_counts = Counter(
        definition.definition_id for definition in assessment.viewer.hand_definitions
    )
    return max(
        legal_selections,
        key=lambda selection: (
            mulligan_selection_score(
                selection,
                hand_by_id,
                definition_counts,
                weights=DEFAULT_MULLIGAN_POLICY.baseline,
            ),
            -len(selection.cards_to_replace),
            tuple(str(card_id) for card_id in selection.cards_to_replace),
        ),
    )
