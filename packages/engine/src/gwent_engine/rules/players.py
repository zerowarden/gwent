from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState, PlayerState


def other_player_from_state(state: GameState, player_id: PlayerId) -> PlayerState:
    return other_player_from_pair(state.players, player_id)


def other_player_from_pair(
    players: tuple[PlayerState, PlayerState],
    player_id: PlayerId,
) -> PlayerState:
    first_player, second_player = players
    if first_player.player_id == player_id:
        return second_player
    return first_player


def replace_player(
    players: tuple[PlayerState, PlayerState],
    updated_player: PlayerState,
) -> tuple[PlayerState, PlayerState]:
    first_player, second_player = players
    if first_player.player_id == updated_player.player_id:
        return updated_player, second_player
    if second_player.player_id == updated_player.player_id:
        return first_player, updated_player
    raise ValueError("Updated player does not match either player in the tuple.")


def opponent_player_id_from_state(state: GameState, player_id: PlayerId) -> PlayerId:
    return other_player_from_state(state, player_id).player_id
