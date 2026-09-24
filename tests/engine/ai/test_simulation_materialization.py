from __future__ import annotations

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.simulation import (
    SIMULATION_HIDDEN_CARD_DEFINITION,
    materialize_player_simulation,
)
from gwent_engine.core import ChoiceSourceKind, Row, Zone
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.events import LeaderAbilityResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.invariants import check_game_state_invariants
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action_with_intermediate_state
from gwent_engine.core.state import GameState

from ..scenario_builder import card, rows, scenario
from ..support import CARD_REGISTRY, LEADER_REGISTRY, PLAYER_ONE_ID, PLAYER_TWO_ID


def _materialize(state: GameState):
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    return materialize_player_simulation(
        observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )


def test_materialization_retains_viewer_and_public_cards() -> None:
    state = (
        scenario("materialize_public")
        .player(
            "p1",
            hand=[card("p1_hand_archer", "scoiatael_dol_blathanna_archer")],
            deck=[card("p1_deck_geralt", "neutral_geralt")],
            discard=[card("p1_discard_horn", "neutral_commanders_horn")],
            board=rows(close=[card("p1_board_defender", "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            hand=[card("p2_hidden_a", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
            discard=[card("p2_public_discard", "scoiatael_mahakaman_defender")],
            board=rows(ranged=[card("p2_public_archer", "scoiatael_dol_blathanna_archer")]),
        )
        .build()
    )

    materialized = _materialize(state).state

    assert materialized.player(PLAYER_ONE_ID).hand == state.player(PLAYER_ONE_ID).hand
    assert materialized.player(PLAYER_ONE_ID).discard == state.player(PLAYER_ONE_ID).discard
    assert materialized.player(PLAYER_TWO_ID).discard == state.player(PLAYER_TWO_ID).discard
    assert materialized.card(CardInstanceId("p2_public_discard")).definition_id == (
        state.card(CardInstanceId("p2_public_discard")).definition_id
    )
    assert materialized.player(PLAYER_TWO_ID).rows.ranged == state.player(PLAYER_TWO_ID).rows.ranged
    assert len(materialized.player(PLAYER_TWO_ID).hand) == 1
    assert len(materialized.player(PLAYER_TWO_ID).deck) == 1
    check_game_state_invariants(materialized, card_registry=CARD_REGISTRY)


def test_materialization_replaces_opponent_hidden_identities() -> None:
    state = (
        scenario("materialize_hidden")
        .player(
            "p1",
            hand=[card("p1_hand_archer", "scoiatael_dol_blathanna_archer")],
            deck=[card("p1_deck_geralt", "neutral_geralt")],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_a", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .build()
    )

    simulation = _materialize(state)
    materialized = simulation.state
    authoritative_hidden_ids = set(state.player(PLAYER_TWO_ID).hand) | set(
        state.player(PLAYER_TWO_ID).deck
    )
    materialized_ids = {card.instance_id for card in materialized.card_instances}

    assert not materialized_ids & authoritative_hidden_ids
    assert {
        materialized.card(card_id).definition_id
        for card_id in (
            *materialized.player(PLAYER_TWO_ID).hand,
            *materialized.player(PLAYER_TWO_ID).deck,
        )
    } == {SIMULATION_HIDDEN_CARD_DEFINITION.definition_id}
    assert materialized.player(PLAYER_ONE_ID).hand == ("p1_hand_archer",)
    assert (
        simulation.card_registry.get(SIMULATION_HIDDEN_CARD_DEFINITION.definition_id)
        == SIMULATION_HIDDEN_CARD_DEFINITION
    )


def test_synthetic_hidden_ids_are_zone_ordinal_identifiers() -> None:
    state = (
        scenario("materialize_synthetic_ids")
        .player("p1", deck=[card("p1_deck_geralt", "neutral_geralt")])
        .player(
            "p2",
            hand=[card("p2_hidden_a", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .build()
    )

    materialized = _materialize(state).state

    opponent_hand_ids = tuple(str(card_id) for card_id in materialized.player(PLAYER_TWO_ID).hand)
    opponent_deck_ids = tuple(str(card_id) for card_id in materialized.player(PLAYER_TWO_ID).deck)
    viewer_deck_ids = tuple(str(card_id) for card_id in materialized.player(PLAYER_ONE_ID).deck)

    assert opponent_hand_ids == ("opponent_hidden_hand_001",)
    assert opponent_deck_ids == ("opponent_hidden_deck_001",)
    assert viewer_deck_ids == ("viewer_unknown_deck_001",)


def test_materialization_preserves_viewer_deck_composition_without_order() -> None:
    state_a = (
        scenario("materialize_viewer_deck")
        .player(
            "p1",
            deck=[
                card("p1_deck_geralt", "neutral_geralt"),
                card("p1_deck_horn", "neutral_commanders_horn"),
            ],
        )
        .build()
    )
    state_b = (
        scenario("materialize_viewer_deck")
        .player(
            "p1",
            deck=[
                card("p1_deck_horn", "neutral_commanders_horn"),
                card("p1_deck_geralt", "neutral_geralt"),
            ],
        )
        .build()
    )

    materialized_a = _materialize(state_a).state
    materialized_b = _materialize(state_b).state
    definitions = sorted(
        str(materialized_a.card(card_id).definition_id)
        for card_id in materialized_a.player(PLAYER_ONE_ID).deck
    )

    assert definitions == ["neutral_commanders_horn", "neutral_geralt"]
    assert state_fingerprint(materialized_a) == state_fingerprint(materialized_b)


def test_materialization_is_deterministic() -> None:
    state = (
        scenario("materialize_deterministic")
        .player("p1", hand=[card("p1_hand_archer", "scoiatael_dol_blathanna_archer")])
        .player(
            "p2",
            hand=[card("p2_hidden_a", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .build()
    )

    first = _materialize(state).state
    second = _materialize(state).state

    assert state_fingerprint(first) == state_fingerprint(second)


def test_materialization_maps_deck_pending_choice_targets_to_synthetic_instances() -> None:
    state = (
        scenario("materialize_leader_pending_choice")
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_destroyer_of_worlds",
            hand=[
                card("p1_discard_recruit", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_discard_archer", "scoiatael_dol_blathanna_archer"),
            ],
            deck=[
                card("p1_pick_geralt", "neutral_geralt"),
                card("p1_skip_trebuchet", "northern_realms_trebuchet"),
            ],
        )
        .leader_choice(
            choice_id="leader_discard_and_choose_choice",
            player_id="p1",
            source_leader_id="monsters_eredin_destroyer_of_worlds",
            legal_target_card_instance_ids=(
                "p1_discard_recruit",
                "p1_discard_archer",
                "p1_pick_geralt",
                "p1_skip_trebuchet",
            ),
            min_selections=3,
            max_selections=3,
        )
        .build()
    )

    simulation = _materialize(state)
    materialized = simulation.state
    assert materialized.pending_choice is not None

    for card_id in materialized.pending_choice.legal_target_card_instance_ids:
        _ = materialized.card(card_id)

    deck_targets = tuple(
        card_id
        for card_id in materialized.pending_choice.legal_target_card_instance_ids
        if materialized.card(card_id).zone == Zone.DECK
    )
    assert len(deck_targets) == 2
    assert all(str(card_id).startswith("viewer_unknown_deck_") for card_id in deck_targets)
    assert set(materialized.player(PLAYER_ONE_ID).hand) == {
        "p1_discard_recruit",
        "p1_discard_archer",
    }
    check_game_state_invariants(materialized, card_registry=CARD_REGISTRY)


def test_translated_viewer_deck_action_applies_to_simulation() -> None:
    state = (
        scenario("materialize_leader_weather")
        .player(
            "p1",
            faction="northern_realms",
            leader_id="northern_realms_foltest_king_of_temeria",
            deck=[card("p1_deck_fog", "neutral_impenetrable_fog")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    simulation = materialize_player_simulation(
        observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    leader_action = next(
        action for action in legal_actions if isinstance(action, UseLeaderAbilityAction)
    )

    translated = simulation.translate_action(leader_action)
    assert isinstance(translated, UseLeaderAbilityAction)
    target_card_instance_id = translated.target_card_instance_id
    assert target_card_instance_id is not None
    assert translated != leader_action
    assert (
        simulation.state.card(target_card_instance_id).definition_id == "neutral_impenetrable_fog"
    )
    next_state, events, _ = apply_action_with_intermediate_state(
        simulation.state,
        translated,
        rng=SeededRandom(0),
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.used
    assert any(
        isinstance(event, LeaderAbilityResolvedEvent)
        and event.played_card_instance_id == target_card_instance_id
        and event.affected_row == Row.RANGED
        for event in events
    )


def test_materialization_only_uses_visible_pending_choice() -> None:
    state = (
        scenario("materialize_opponent_pending_choice")
        .player("p1", hand=[card("p1_hand_archer", "scoiatael_dol_blathanna_archer")])
        .player(
            "p2",
            faction="monsters",
            leader_id="monsters_eredin_destroyer_of_worlds",
            hand=[card("p2_hidden_hand", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .pending_choice(
            choice_id="hidden_leader_choice",
            player_id="p2",
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_leader_id="monsters_eredin_destroyer_of_worlds",
            legal_target_card_instance_ids=("p2_hidden_hand", "p2_hidden_deck"),
            min_selections=2,
            max_selections=2,
        )
        .current_player("p2")
        .build()
    )

    materialized = _materialize(state).state

    assert materialized.pending_choice is None
