from dataclasses import replace

from gwent_engine.core import Row, Zone
from gwent_engine.core.config import MAX_HAND_SIZE
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import CardInstance, GameState, PlayerState, RowState
from gwent_engine.rules.players import other_player_from_pair


def append_to_row(rows: RowState, row: Row, card_id: CardInstanceId) -> RowState:
    match row:
        case Row.CLOSE:
            return replace(rows, close=(*rows.close, card_id))
        case Row.RANGED:
            return replace(rows, ranged=(*rows.ranged, card_id))
        case Row.SIEGE:
            return replace(rows, siege=(*rows.siege, card_id))


def remove_card_from_rows(rows: RowState, card_id: CardInstanceId) -> RowState:
    return RowState(
        close=tuple(existing_id for existing_id in rows.close if existing_id != card_id),
        ranged=tuple(existing_id for existing_id in rows.ranged if existing_id != card_id),
        siege=tuple(existing_id for existing_id in rows.siege if existing_id != card_id),
    )


def replace_row_card(
    rows: RowState,
    row: Row,
    existing_card_id: CardInstanceId,
    replacement_card_id: CardInstanceId,
) -> RowState:
    updated_cards = tuple(
        replacement_card_id if card_id == existing_card_id else card_id
        for card_id in rows.cards_for(row)
    )
    match row:
        case Row.CLOSE:
            return replace(rows, close=updated_cards)
        case Row.RANGED:
            return replace(rows, ranged=updated_cards)
        case Row.SIEGE:
            return replace(rows, siege=updated_cards)


def replace_card_instance(
    card_instances: tuple[CardInstance, ...],
    updated_card: CardInstance,
) -> tuple[CardInstance, ...]:
    return tuple(
        updated_card if card.instance_id == updated_card.instance_id else card
        for card in card_instances
    )


def replace_card_instances(
    card_instances: tuple[CardInstance, ...],
    updated_cards: dict[CardInstanceId, CardInstance],
) -> tuple[CardInstance, ...]:
    return tuple(updated_cards.get(card.instance_id, card) for card in card_instances)


def next_player_after_non_pass_action(state: GameState, acting_player_id: PlayerId) -> PlayerId:
    opponent = other_player_from_pair(state.players, acting_player_id)
    if opponent.has_passed:
        return acting_player_id
    return opponent.player_id


def drawable_card_ids(player: PlayerState, requested_count: int) -> tuple[CardInstanceId, ...]:
    available_hand_slots = max(0, MAX_HAND_SIZE - len(player.hand))
    draw_count = min(requested_count, available_hand_slots, len(player.deck))
    return player.deck[:draw_count]


def discard_owned_weather_cards(
    state: GameState,
    player: PlayerState,
    cleared_weather_ids: tuple[CardInstanceId, ...],
) -> PlayerState:
    owned_weather_cards = tuple(
        card_id for card_id in cleared_weather_ids if state.card(card_id).owner == player.player_id
    )
    return replace(player, discard=player.discard + owned_weather_cards)


def remove_from_play_source_zone(
    player: PlayerState,
    zone: Zone,
    card_id: CardInstanceId,
) -> PlayerState:
    match zone:
        case Zone.DECK:
            return replace(
                player,
                deck=tuple(existing_id for existing_id in player.deck if existing_id != card_id),
            )
        case Zone.HAND:
            return replace(
                player,
                hand=tuple(existing_id for existing_id in player.hand if existing_id != card_id),
            )
        case Zone.DISCARD:
            return replace(
                player,
                discard=tuple(
                    existing_id for existing_id in player.discard if existing_id != card_id
                ),
            )
        case _:
            pass
    raise ValueError(f"Unsupported play-source zone: {zone!r}")
