from gwent_engine.ai.arena import create_bot, run_bot_match
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.ids import GameId, PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.decks import load_sample_decks

from tests.engine.support import CARD_REGISTRY, DATA_DIR, LEADER_REGISTRY


def test_run_bot_match_completes_seeded_game() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    run = run_bot_match(
        game_id=GameId("arena_test_game"),
        player_one_bot=create_bot("greedy", bot_id="p1_bot"),
        player_two_bot=create_bot("random", bot_id="p2_bot", seed=8),
        player_one_deck=deck_by_id["monsters_muster_swarm_strict"],
        player_two_deck=deck_by_id["nilfgaard_spy_medic_control_strict"],
        starting_player=PlayerId("p1"),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        rng=SeededRandom(17),
    )

    assert run.steps
    assert run.final_state.phase == Phase.MATCH_ENDED
    assert run.final_state.status == GameStatus.MATCH_ENDED
    assert run.player_one_bot_name == "GreedyBot"
    assert run.player_two_bot_name == "RandomBot"


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


def test_heuristic_bot_outperforms_random_in_seeded_series() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    heuristic_points = 0.0
    random_points = 0.0
    for seed in (3, 11, 29, 41):
        run = run_bot_match(
            game_id=GameId(f"heuristic_vs_random_{seed}"),
            player_one_bot=create_bot("heuristic", bot_id=f"heuristic_{seed}"),
            player_two_bot=create_bot("random", bot_id=f"random_{seed}", seed=seed),
            player_one_deck=deck_by_id["monsters_muster_swarm_strict"],
            player_two_deck=deck_by_id["monsters_muster_swarm_strict"],
            starting_player=PlayerId("p1"),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            rng=SeededRandom(seed),
        )
        if run.final_state.match_winner == PlayerId("p1"):
            heuristic_points += 1.0
        elif run.final_state.match_winner == PlayerId("p2"):
            random_points += 1.0
        else:
            heuristic_points += 0.5
            random_points += 0.5

    assert heuristic_points > random_points


def test_heuristic_bot_completes_seeded_series_against_greedy() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    for seed in (5, 17, 37):
        run = run_bot_match(
            game_id=GameId(f"heuristic_vs_greedy_{seed}"),
            player_one_bot=create_bot("heuristic", bot_id=f"heuristic_{seed}"),
            player_two_bot=create_bot("greedy", bot_id=f"greedy_{seed}"),
            player_one_deck=deck_by_id["nilfgaard_spy_medic_control_strict"],
            player_two_deck=deck_by_id["monsters_muster_swarm_strict"],
            starting_player=PlayerId("p1"),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            rng=SeededRandom(seed),
        )

        assert run.final_state.phase == Phase.MATCH_ENDED
        assert run.final_state.status == GameStatus.MATCH_ENDED
        assert run.player_one_bot_name == "HeuristicBot"
        assert run.player_two_bot_name == "GreedyBot"


def test_search_bot_completes_seeded_game() -> None:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    deck_by_id = {str(deck.deck_id): deck for deck in decks}

    run = run_bot_match(
        game_id=GameId("search_vs_random_seeded"),
        player_one_bot=create_bot("search", bot_id="search_bot"),
        player_two_bot=create_bot("random", bot_id="random_bot", seed=13),
        player_one_deck=deck_by_id["nilfgaard_spy_medic_control_strict"],
        player_two_deck=deck_by_id["monsters_muster_swarm_strict"],
        starting_player=PlayerId("p1"),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        rng=SeededRandom(13),
    )

    assert run.final_state.phase == Phase.MATCH_ENDED
    assert run.final_state.status == GameStatus.MATCH_ENDED
    assert run.player_one_bot_name == "SearchBot"
    assert run.player_two_bot_name == "RandomBot"
