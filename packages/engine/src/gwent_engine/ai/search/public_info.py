from __future__ import annotations

from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import Zone
from gwent_engine.core.ids import CardDefinitionId, PlayerId
from gwent_engine.core.state import CardInstance, GameState
from gwent_engine.rules.players import opponent_player_id_from_state

# Search is allowed to use the viewer's own private zones, but it should not
# depend on the opponent's hidden hand/deck identities. Hidden opponent cards
# are therefore collapsed to one stable placeholder definition before search
# evaluation or reply modeling begins. This preserves:
# - hidden zone counts
# - legal public state transitions
# - deterministic reducer behavior for searched public lines
# while removing the specific hidden card identities from the search surface.
PUBLIC_INFO_HIDDEN_CARD_DEFINITION_ID = CardDefinitionId("scoiatael_mahakaman_defender")


def redact_private_information(
    state: GameState,
    *,
    viewer_player_id: PlayerId,
    card_registry: CardRegistry,
) -> GameState:
    _ = card_registry.get(PUBLIC_INFO_HIDDEN_CARD_DEFINITION_ID)
    opponent_id = opponent_player_id_from_state(state, viewer_player_id)
    redacted_cards = tuple(
        _redact_hidden_card(card, opponent_id=opponent_id) for card in state.card_instances
    )
    if redacted_cards == state.card_instances:
        return state
    return replace(state, card_instances=redacted_cards)


def _redact_hidden_card(card: CardInstance, *, opponent_id: PlayerId) -> CardInstance:
    if card.owner != opponent_id or card.zone not in {Zone.HAND, Zone.DECK}:
        return card
    return replace(card, definition_id=PUBLIC_INFO_HIDDEN_CARD_DEFINITION_ID)
