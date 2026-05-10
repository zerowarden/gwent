from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.events import CardTransformedEvent, GameEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState
from gwent_engine.rules.row_effects import row_has_active_mardroeme
from gwent_engine.rules.state_ops import replace_card_instance


def apply_berserker_transformations_for_row(
    state: GameState,
    *,
    card_registry: CardRegistry,
    battlefield_side: PlayerId,
    row: Row,
    event_id_start: int,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if not row_has_active_mardroeme(state, card_registry, battlefield_side, row):
        return state, ()

    current_state = state
    events: list[GameEvent] = []
    for card_id in current_state.player(battlefield_side).rows.cards_for(row):
        card = current_state.card(card_id)
        definition = card_registry.get(card.definition_id)
        if (
            definition.card_type != CardType.UNIT
            or AbilityKind.BERSERKER not in definition.ability_kinds
            or definition.transforms_into_definition_id is None
        ):
            continue
        transformed_definition_id = definition.transforms_into_definition_id
        updated_card = replace(card, definition_id=transformed_definition_id)
        current_state = replace(
            current_state,
            card_instances=replace_card_instance(current_state.card_instances, updated_card),
        )
        events.append(
            CardTransformedEvent(
                event_id=event_id_start + len(events),
                player_id=card.owner,
                card_instance_id=card_id,
                previous_definition_id=card.definition_id,
                new_definition_id=transformed_definition_id,
                affected_row=row,
            )
        )
    return current_state, tuple(events)
