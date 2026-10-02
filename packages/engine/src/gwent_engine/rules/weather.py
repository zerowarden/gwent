from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import WEATHER_ROWS_BY_ABILITY, AbilityKind, CardType, Row, Zone
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import CardInstance, GameState, PlayerState
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.rules.state_ops import card_in_zone, discard_owned_weather_cards


def is_weather_ability(ability_kind: AbilityKind) -> bool:
    return ability_kind in WEATHER_ROWS_BY_ABILITY


def weather_rows_for(ability_kind: AbilityKind) -> tuple[Row, ...]:
    return WEATHER_ROWS_BY_ABILITY[ability_kind]


def weather_row_for(ability_kind: AbilityKind) -> Row:
    return weather_rows_for(ability_kind)[0]


def clear_weather_cards(
    state: GameState,
    cleared_weather_ids: tuple[CardInstanceId, ...],
) -> tuple[tuple[PlayerState, PlayerState], dict[CardInstanceId, CardInstance]]:
    """Discard the given battlefield weather cards and return the resulting piles."""
    first_player, second_player = state.players
    updated_players = (
        discard_owned_weather_cards(state, first_player, cleared_weather_ids),
        discard_owned_weather_cards(state, second_player, cleared_weather_ids),
    )
    updated_cards = {
        card_id: card_in_zone(state.card(card_id), zone=Zone.DISCARD)
        for card_id in cleared_weather_ids
    }
    return updated_players, updated_cards


def weather_card_affects_row(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
    row: Row,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    if definition.card_type != CardType.SPECIAL:
        return False
    return row in weather_rows_for(special_weather_ability_kind(definition))


def special_weather_ability_kind(definition: CardDefinition) -> AbilityKind:
    ability_kind = special_ability_kind(definition)
    if not is_weather_ability(ability_kind):
        raise ValueError(f"Card ability {ability_kind!r} is not a weather ability.")
    return ability_kind
