from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState
from gwent_engine.rules.row_effects import special_ability_kind

WEATHER_ROWS_BY_ABILITY = {
    AbilityKind.BITING_FROST: (Row.CLOSE,),
    AbilityKind.IMPENETRABLE_FOG: (Row.RANGED,),
    AbilityKind.TORRENTIAL_RAIN: (Row.SIEGE,),
    AbilityKind.SKELLIGE_STORM: (Row.RANGED, Row.SIEGE),
}


def is_weather_ability(ability_kind: AbilityKind) -> bool:
    return ability_kind in WEATHER_ROWS_BY_ABILITY


def weather_rows_for(ability_kind: AbilityKind) -> tuple[Row, ...]:
    return WEATHER_ROWS_BY_ABILITY[ability_kind]


def weather_row_for(ability_kind: AbilityKind) -> Row:
    return weather_rows_for(ability_kind)[0]


def active_weather_cards(state: GameState) -> tuple[CardInstanceId, ...]:
    return state.battlefield_weather.all_cards()


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
