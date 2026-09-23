from __future__ import annotations

from collections.abc import Mapping, Sequence

from gwent_engine.ai.observations import ObservedCard, PlayerObservation
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import CardType
from gwent_engine.core.actions import GameAction, LeaveAction
from gwent_engine.core.ids import CardInstanceId


def is_non_hero_unit(definition: CardDefinition) -> bool:
    return definition.card_type == CardType.UNIT and not definition.is_hero


def visible_definitions(
    observation: PlayerObservation,
    card_registry: CardRegistry,
    *,
    include_viewer_deck: bool = False,
) -> dict[CardInstanceId, CardDefinition]:
    visible_cards: list[ObservedCard] = list(observation.viewer_hand)
    if include_viewer_deck:
        visible_cards.extend(observation.viewer_deck)
    for player in observation.public_state.players:
        visible_cards.extend(player.discard)
        visible_cards.extend(player.rows.close)
        visible_cards.extend(player.rows.ranged)
        visible_cards.extend(player.rows.siege)
    weather = observation.public_state.battlefield_weather
    visible_cards.extend(weather.close)
    visible_cards.extend(weather.ranged)
    visible_cards.extend(weather.siege)
    return {card.instance_id: card_registry.get(card.definition_id) for card in visible_cards}


def filter_non_leave_actions(legal_actions: Sequence[GameAction]) -> tuple[GameAction, ...]:
    actions = tuple(legal_actions)
    non_leave_actions = tuple(action for action in actions if not isinstance(action, LeaveAction))
    return non_leave_actions or actions


def build_viewer_hand_definition_index(
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> dict[CardInstanceId, CardDefinition]:
    return {
        card.instance_id: card_registry.get(card.definition_id) for card in observation.viewer_hand
    }


def viewer_hand_definition(
    card_instance_id: CardInstanceId,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> CardDefinition | None:
    if viewer_hand_definitions is not None:
        return viewer_hand_definitions.get(card_instance_id)
    for card in observation.viewer_hand:
        if card.instance_id == card_instance_id:
            return card_registry.get(card.definition_id)
    return None
