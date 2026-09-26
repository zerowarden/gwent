import pytest
from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.policy import DEFAULT_SEARCH_CONFIG
from gwent_engine.ai.search.turn_resolution import TurnSearchResolver
from gwent_engine.core import Row
from gwent_engine.core.actions import GameAction, PlayCardAction
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState

from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_search_candidate_samples_are_independent_of_prior_candidate_evaluation() -> None:
    state = (
        scenario("search_branch_randomness")
        .player(
            PLAYER_ONE_ID,
            faction="nilfgaard",
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=[
                card("p1_medic_a", "nilfgaard_etolian_auxilary_archer"),
                card("p1_medic_b", "nilfgaard_etolian_auxilary_archer"),
            ],
            discard=[
                card("p1_discard_catapult", "northern_realms_catapult"),
                card("p1_discard_archer", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_hidden_unit", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    resolver = TurnSearchResolver(
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    target_action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_medic_a"),
        target_row=Row.RANGED,
    )
    unrelated_stochastic_action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_medic_b"),
        target_row=Row.RANGED,
    )

    target_line = resolver.resolve_root_action_with_reply(state, target_action)
    _ = resolver.resolve_root_action_with_reply(state, unrelated_stochastic_action)
    repeated_target_line = resolver.resolve_root_action_with_reply(state, target_action)

    assert repeated_target_line == target_line


def test_root_actions_share_sampled_deck_worlds_and_average_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import defaultdict
    from statistics import fmean

    from gwent_engine.ai.action_ids import action_to_id
    from gwent_engine.ai.actions import enumerate_legal_actions
    from gwent_engine.ai.observations import build_player_observation
    from gwent_engine.ai.search.engine import build_search_engine
    from gwent_engine.ai.search.types import SearchLine

    state = (
        scenario("shared_deck_worlds")
        .player(
            "p1",
            hand=[card("unit", "scoiatael_mahakaman_defender")],
            deck=[
                card("a", "neutral_geralt"),
                card("b", "neutral_impenetrable_fog"),
                card("c", "northern_realms_catapult"),
                card("d", "neutral_decoy"),
            ],
        )
        .player("p2", hand=[card("enemy", "neutral_geralt")])
        .build()
    )
    worlds: dict[str, list[tuple[CardInstanceId, ...]]] = defaultdict(list)
    values: dict[str, list[float]] = defaultdict(list)

    def resolve(self: TurnSearchResolver, state: GameState, action: GameAction) -> SearchLine:
        del self
        deck = state.player(PLAYER_ONE_ID).deck
        key = action_to_id(action)
        worlds[key].append(deck)
        value = float(CARD_REGISTRY.get(state.card(deck[0]).definition_id).base_strength)
        values[key].append(value)
        return SearchLine(actions=(action,), value=value)

    monkeypatch.setattr(TurnSearchResolver, "resolve_root_action_with_reply", resolve)
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG, profile_definition=DEFAULT_BASE_PROFILE, bot_id="worlds"
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    actions = enumerate_legal_actions(
        state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY, leader_registry=LEADER_REGISTRY
    )
    result = engine.choose_action(
        observation, actions, card_registry=CARD_REGISTRY, leader_registry=LEADER_REGISTRY
    )
    assert len(worlds) > 1
    assert all(sampled == next(iter(worlds.values())) for sampled in worlds.values())
    assert len(set(next(iter(worlds.values())))) > 1
    for evaluation in result.evaluations:
        assert evaluation.line.value == fmean(values[action_to_id(evaluation.action)])
    assert (
        engine.choose_action(
            observation, actions, card_registry=CARD_REGISTRY, leader_registry=LEADER_REGISTRY
        )
        == result
    )
