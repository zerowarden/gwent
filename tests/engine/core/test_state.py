import pytest
from gwent_engine.core.errors import UnknownCardInstanceError, UnknownPlayerError
from gwent_engine.core.ids import CardInstanceId, PlayerId

from tests.engine.support import build_sample_game_state


def test_state_card_and_player_lookup_use_indexed_access() -> None:
    state = build_sample_game_state()
    player = state.players[0]
    card = state.card_instances[0]

    assert state.player(player.player_id) is player
    assert state.card(card.instance_id) is card


def test_state_lookup_raises_for_unknown_ids() -> None:
    state = build_sample_game_state()

    with pytest.raises(UnknownPlayerError):
        _ = state.player(PlayerId("missing"))

    with pytest.raises(UnknownCardInstanceError):
        _ = state.card(CardInstanceId("missing"))


def test_state_cached_or_compute_reuses_computed_value() -> None:
    state = build_sample_game_state()
    calls = 0

    def build_value() -> tuple[str, int]:
        nonlocal calls
        calls += 1
        return ("cached", calls)

    first = state.cached_or_compute("example", build_value)
    second = state.cached_or_compute("example", build_value)

    assert first == ("cached", 1)
    assert second is first
    assert calls == 1
