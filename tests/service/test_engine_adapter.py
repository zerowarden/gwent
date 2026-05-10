from gwent_engine.core.ids import DeckId
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.engine.contracts import CreateMatchStateSpec, EnginePlayerDeckSpec


def test_engine_adapter_can_create_initial_match_state() -> None:
    adapter = GwentEngineAdapter()

    state = adapter.create_match_state(
        CreateMatchStateSpec(
            game_id="service_match_1",
            players=(
                EnginePlayerDeckSpec(
                    player_id="p1", deck_id=str(DeckId("monsters_muster_swarm_strict"))
                ),
                EnginePlayerDeckSpec(
                    player_id="p2",
                    deck_id=str(DeckId("nilfgaard_spy_medic_control_strict")),
                ),
            ),
            rng_seed=7,
        )
    )

    assert str(state.game_id) == "service_match_1"
    assert state.phase.value == "not_started"
    assert tuple(str(player.player_id) for player in state.players) == ("p1", "p2")
    assert state.rng_seed == 7


def test_engine_adapter_round_trips_serialized_state() -> None:
    adapter = GwentEngineAdapter()
    state = adapter.create_match_state(
        CreateMatchStateSpec(
            game_id="service_match_2",
            players=(
                EnginePlayerDeckSpec(player_id="p1", deck_id="monsters_muster_swarm_strict"),
                EnginePlayerDeckSpec(player_id="p2", deck_id="nilfgaard_spy_medic_control_strict"),
            ),
        )
    )

    payload = adapter.serialize_state(state)
    round_tripped = adapter.deserialize_state(payload)

    assert adapter.serialize_state(round_tripped) == payload
