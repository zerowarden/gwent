from gwent_engine.ai.actions import (
    action_to_id,
    enumerate_legal_actions,
    enumerate_mulligan_selections,
)
from gwent_engine.ai.agents.random_bot import RandomBot
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.actions import (
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    build_sample_game_state,
    build_started_game_state,
)


def test_random_bot_chooses_legal_mulligan_selection() -> None:
    state, _ = build_started_game_state()
    bot = RandomBot(seed=7)
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)

    selected = bot.choose_mulligan(
        observation,
        legal_selections,
        card_registry=CARD_REGISTRY,
    )

    assert selected in legal_selections


def test_random_bot_chooses_legal_turn_action() -> None:
    state = (
        scenario("random_turn_action")
        .player(
            "p1",
            hand=[
                card("p1_close_unit_card", "scoiatael_mahakaman_defender"),
                card("p1_ranged_unit_card", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    selected = RandomBot(seed=3).choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected in legal_actions


def test_random_bot_does_not_pass_when_other_turn_actions_exist() -> None:
    state = (
        scenario("random_no_pass_when_actions_exist")
        .player(
            "p1",
            hand=[
                card("p1_close_unit_card", "scoiatael_mahakaman_defender"),
                card("p1_ranged_unit_card", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    selected = RandomBot(seed=0).choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert PassAction(player_id=PLAYER_ONE_ID) in legal_actions
    assert not isinstance(selected, PassAction)


def test_random_bot_chooses_legal_pending_choice_action() -> None:
    state = (
        scenario("random_pending_choice")
        .player(
            "p1",
            hand=[card("p1_decoy_trick_card", "neutral_decoy")],
            board=rows(
                close=[card("p1_frontline_defender", "scoiatael_mahakaman_defender")],
                ranged=[card("p1_ranged_archer", "scoiatael_dol_blathanna_archer")],
            ),
        )
        .player(
            "p2",
            hand=[card("p2_reserve_unit", "scoiatael_vrihedd_brigade_recruit")],
        )
        .build()
    )
    pending_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_decoy_trick_card"),
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    legal_actions = enumerate_legal_actions(pending_state, player_id=PLAYER_ONE_ID)

    selected = RandomBot(seed=1).choose_pending_choice(
        build_player_observation(pending_state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected in legal_actions
    assert isinstance(selected, ResolveChoiceAction)


def test_random_bot_is_deterministic_for_same_seed() -> None:
    state = (
        scenario("random_deterministic")
        .player(
            "p1",
            hand=[
                card("p1_close_unit_card", "scoiatael_mahakaman_defender"),
                card("p1_ranged_unit_card", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    first_action = RandomBot(seed=11).choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
    )
    second_action = RandomBot(seed=11).choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert action_to_id(first_action) == action_to_id(second_action)


def test_random_bot_completes_seeded_game_legally() -> None:
    rng = SeededRandom(101)
    state = build_sample_game_state()
    bots = {
        PLAYER_ONE_ID: RandomBot(seed=11, bot_id="random_p1"),
        PLAYER_TWO_ID: RandomBot(seed=29, bot_id="random_p2"),
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
        raise AssertionError("Seeded random-bot match did not finish within 256 actions.")

    assert state.phase == Phase.MATCH_ENDED
    assert state.status == GameStatus.MATCH_ENDED
