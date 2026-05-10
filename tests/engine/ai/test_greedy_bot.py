from gwent_engine.ai.actions import enumerate_legal_actions, enumerate_mulligan_selections
from gwent_engine.ai.agents.greedy_bot import GreedyBot
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import ChoiceSourceKind, GameStatus, Phase, Row
from gwent_engine.core.actions import (
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.ids import CardInstanceId, ChoiceId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    build_sample_game_state,
)


def test_greedy_bot_prefers_stronger_playable_unit() -> None:
    state = (
        scenario("greedy_stronger_unit")
        .player(
            "p1",
            hand=[
                card("p1_archer_in_hand", "scoiatael_dol_blathanna_archer"),
                card("p1_defender_in_hand", "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    selected = GreedyBot().choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_defender_in_hand"),
        target_row=Row.CLOSE,
    )


def test_greedy_bot_prefers_higher_value_pending_choice_target() -> None:
    state = (
        scenario("greedy_pending_choice")
        .player(
            "p1",
            hand=[card("p1_source_decoy", "neutral_decoy")],
            board=rows(
                close=[card("p1_stronger_target", "scoiatael_mahakaman_defender")],
                ranged=[card("p1_weaker_target", "scoiatael_dol_blathanna_archer")],
            ),
        )
        .card_choice(
            choice_id="pending_choice_1",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_source_decoy",
            legal_target_card_instance_ids=("p1_weaker_target", "p1_stronger_target"),
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    selected = GreedyBot().choose_pending_choice(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("pending_choice_1"),
        selected_card_instance_ids=(CardInstanceId("p1_stronger_target"),),
    )


def test_greedy_bot_prefers_mulliganing_low_value_special_over_hero() -> None:
    state = (
        scenario("greedy_mulligan_state")
        .phase(Phase.MULLIGAN)
        .player(
            "p1",
            hand=[
                card("p1_low_value_weather", "neutral_biting_frost"),
                card("p1_hero_finisher", "neutral_geralt"),
            ],
        )
        .build()
    )
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)

    selected = GreedyBot().choose_mulligan(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_selections,
        card_registry=CARD_REGISTRY,
    )

    assert selected.cards_to_replace == (CardInstanceId("p1_low_value_weather"),)


def test_greedy_bot_uses_deterministic_tie_breaks() -> None:
    state = (
        scenario("greedy_tie_breaks")
        .player(
            "p1",
            hand=[
                card("p1_close_unit_card_a", "scoiatael_mahakaman_defender"),
                card("p1_close_unit_card_b", "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    selected = GreedyBot().choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_close_unit_card_a"),
        target_row=Row.CLOSE,
    )


def test_greedy_bot_completes_seeded_game_legally() -> None:
    rng = SeededRandom(303)
    state = build_sample_game_state()
    bots = {
        PLAYER_ONE_ID: GreedyBot(bot_id="greedy_p1"),
        PLAYER_TWO_ID: GreedyBot(bot_id="greedy_p2"),
    }
    state, _ = apply_action(
        state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=rng,
        leader_registry=LEADER_REGISTRY,
    )

    for _ in range(256):
        if state.status == GameStatus.MATCH_ENDED:
            break
        if state.phase == Phase.MULLIGAN:
            selections = []
            for player_id in (PLAYER_ONE_ID, PLAYER_TWO_ID):
                legal_selections = enumerate_mulligan_selections(state, player_id)
                selection = bots[player_id].choose_mulligan(
                    build_player_observation(state, player_id),
                    legal_selections,
                    card_registry=CARD_REGISTRY,
                    leader_registry=LEADER_REGISTRY,
                )
                assert selection in legal_selections
                selections.append(selection)
            state, _ = apply_action(
                state,
                ResolveMulligansAction(selections=tuple(selections)),
                rng=rng,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )
            continue
        if state.pending_choice is not None:
            acting_player_id = state.pending_choice.player_id
            legal_actions = enumerate_legal_actions(
                state,
                player_id=acting_player_id,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
                rng=rng,
            )
            action = bots[acting_player_id].choose_pending_choice(
                build_player_observation(state, acting_player_id),
                legal_actions,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )
        else:
            acting_player_id = state.current_player
            assert acting_player_id is not None
            legal_actions = enumerate_legal_actions(
                state,
                player_id=acting_player_id,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
                rng=rng,
            )
            action = bots[acting_player_id].choose_action(
                build_player_observation(state, acting_player_id),
                legal_actions,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )
        assert action in legal_actions
        state, _ = apply_action(
            state,
            action,
            rng=rng,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
    else:
        raise AssertionError("Seeded greedy-bot match did not finish within 256 actions.")

    assert state.phase == Phase.MATCH_ENDED
    assert state.status == GameStatus.MATCH_ENDED
