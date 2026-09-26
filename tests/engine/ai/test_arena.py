import pytest
from gwent_engine.ai.arena import create_bot, execute_match
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.ids import GameId, PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.decks import load_sample_decks

from tests.engine.support import CARD_REGISTRY, DATA_DIR, LEADER_REGISTRY


def test_execute_match_completes_seeded_game() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    execution = execute_match(
        game_id=GameId("arena_test_game"),
        player_one_bot=create_bot("greedy", bot_id="p1_bot"),
        player_two_bot=create_bot("random", bot_id="p2_bot", seed=8),
        player_one_deck=deck_by_id["monsters_muster_swarm_strict"],
        player_two_deck=deck_by_id["nilfgaard_spy_medic_control_strict"],
        starting_player=PlayerId("p1"),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        rng=SeededRandom(17),
        action_budget=512,
    )

    assert execution.completed
    assert execution.failure is None
    assert execution.final_state is not None
    assert execution.final_state.phase == Phase.MATCH_ENDED
    assert execution.final_state.status == GameStatus.MATCH_ENDED
    assert execution.match_winner == execution.final_state.match_winner


def test_create_bot_supports_heuristic() -> None:
    bot = create_bot("heuristic", bot_id="heuristic_bot")

    assert bot.display_name == "HeuristicBot"


def test_create_bot_supports_named_heuristic_profile() -> None:
    bot = create_bot("heuristic:conservative", bot_id="heuristic_bot")

    assert bot.display_name == "HeuristicBot[conservative]"


def test_create_bot_supports_search() -> None:
    bot = create_bot("search", bot_id="search_bot")

    assert bot.display_name == "SearchBot"


def test_create_bot_supports_named_search_profile() -> None:
    bot = create_bot("search:conservative", bot_id="search_bot")

    assert bot.display_name == "SearchBot[conservative]"


@pytest.mark.parametrize("family", ["random", "greedy"])
def test_create_bot_rejects_profile_for_profileless_family(family: str) -> None:
    with pytest.raises(ValueError, match="does not accept a profile"):
        _ = create_bot(f"{family}:neutral", bot_id="bot")


@pytest.mark.parametrize("family", ["greedy", "heuristic", "search"])
def test_create_bot_rejects_seed_for_deterministic_family(family: str) -> None:
    with pytest.raises(ValueError, match="does not accept a seed"):
        _ = create_bot(family, bot_id="bot", seed=1)


@pytest.mark.parametrize("profile_id", ["does-not-exist", "baseline", "aggro", "tempo"])
def test_create_bot_rejects_unrecognized_profile(profile_id: str) -> None:
    with pytest.raises(ValueError, match="Unknown profile id"):
        _ = create_bot(f"heuristic:{profile_id}", bot_id="bot")


def test_create_bot_rejects_unknown_family() -> None:
    with pytest.raises(ValueError, match="Unknown bot family"):
        _ = create_bot("mystery", bot_id="bot")


def test_heuristic_bot_outperforms_random_in_seeded_series() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    heuristic_points = 0.0
    random_points = 0.0
    for seed in (3, 11, 29, 41):
        execution = execute_match(
            game_id=GameId(f"heuristic_vs_random_{seed}"),
            player_one_bot=create_bot("heuristic", bot_id=f"heuristic_{seed}"),
            player_two_bot=create_bot("random", bot_id=f"random_{seed}", seed=seed),
            player_one_deck=deck_by_id["monsters_muster_swarm_strict"],
            player_two_deck=deck_by_id["monsters_muster_swarm_strict"],
            starting_player=PlayerId("p1"),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            rng=SeededRandom(seed),
            action_budget=512,
        )
        if execution.match_winner == PlayerId("p1"):
            heuristic_points += 1.0
        elif execution.match_winner == PlayerId("p2"):
            random_points += 1.0
        else:
            heuristic_points += 0.5
            random_points += 0.5

    assert heuristic_points > random_points


def test_heuristic_bot_completes_seeded_series_against_greedy() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    for seed in (5, 17, 37):
        execution = execute_match(
            game_id=GameId(f"heuristic_vs_greedy_{seed}"),
            player_one_bot=create_bot("heuristic", bot_id=f"heuristic_{seed}"),
            player_two_bot=create_bot("greedy", bot_id=f"greedy_{seed}"),
            player_one_deck=deck_by_id["nilfgaard_spy_medic_control_strict"],
            player_two_deck=deck_by_id["monsters_muster_swarm_strict"],
            starting_player=PlayerId("p1"),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            rng=SeededRandom(seed),
            action_budget=512,
        )

        assert execution.completed
        assert execution.final_state is not None
        assert execution.final_state.phase == Phase.MATCH_ENDED
        assert execution.final_state.status == GameStatus.MATCH_ENDED


def test_search_bot_completes_seeded_game() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    execution = execute_match(
        game_id=GameId("search_vs_random_seeded"),
        player_one_bot=create_bot("search", bot_id="search_bot"),
        player_two_bot=create_bot("random", bot_id="random_bot", seed=13),
        player_one_deck=deck_by_id["nilfgaard_spy_medic_control_strict"],
        player_two_deck=deck_by_id["monsters_muster_swarm_strict"],
        starting_player=PlayerId("p1"),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        rng=SeededRandom(13),
        action_budget=512,
    )

    assert execution.completed
    assert execution.final_state is not None
    assert execution.final_state.phase == Phase.MATCH_ENDED
    assert execution.final_state.status == GameStatus.MATCH_ENDED
