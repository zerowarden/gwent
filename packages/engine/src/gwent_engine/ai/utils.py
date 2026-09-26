from __future__ import annotations

from collections.abc import Mapping, Sequence

from gwent_engine.ai.observations import ObservedCard, PlayerObservation
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import CardType
from gwent_engine.core.actions import GameAction, LeaveAction
from gwent_engine.core.ids import CardInstanceId


def is_non_hero_unit(definition: CardDefinition) -> bool:
    return definition.card_type == CardType.UNIT and not definition.is_hero


def viewer_deck_instance_ids(observation: PlayerObservation) -> tuple[CardInstanceId, ...]:
    """Return the viewer's own remaining deck instance ids in canonical order."""

    return tuple(
        instance_id
        for entry in observation.viewer_deck_composition
        for instance_id in entry.instance_ids
    )


def viewer_deck_count(observation: PlayerObservation) -> int:
    """Return how many cards remain in the viewer's own deck."""

    return sum(entry.count for entry in observation.viewer_deck_composition)


def viewer_deck_definitions(
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> tuple[CardDefinition, ...]:
    """Return one definition per remaining viewer deck card, preserving multiplicity."""

    return tuple(
        card_registry.get(entry.definition_id)
        for entry in observation.viewer_deck_composition
        for _ in entry.instance_ids
    )


def viewer_deck_definition(
    observation: PlayerObservation,
    card_registry: CardRegistry,
    card_instance_id: CardInstanceId,
) -> CardDefinition | None:
    """Return the definition of one viewer deck instance, or None if not in the deck."""

    for entry in observation.viewer_deck_composition:
        if card_instance_id in entry.instance_ids:
            return card_registry.get(entry.definition_id)
    return None


def visible_definitions(
    observation: PlayerObservation,
    card_registry: CardRegistry,
    *,
    include_viewer_deck: bool = False,
) -> dict[CardInstanceId, CardDefinition]:
    definitions: dict[CardInstanceId, CardDefinition] = {}
    if include_viewer_deck:
        for entry in observation.viewer_deck_composition:
            definition = card_registry.get(entry.definition_id)
            for instance_id in entry.instance_ids:
                definitions[instance_id] = definition
    visible_cards: list[ObservedCard] = list(observation.viewer_hand)
    for player in observation.public_state.players:
        visible_cards.extend(player.discard)
        visible_cards.extend(player.rows.close)
        visible_cards.extend(player.rows.ranged)
        visible_cards.extend(player.rows.siege)
    weather = observation.public_state.battlefield_weather
    visible_cards.extend(weather.close)
    visible_cards.extend(weather.ranged)
    visible_cards.extend(weather.siege)
    for card in visible_cards:
        definitions[card.instance_id] = card_registry.get(card.definition_id)
    return definitions


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
