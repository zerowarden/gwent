from __future__ import annotations

from collections.abc import Callable
from typing import cast

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.arena import create_bot, parse_bot_spec, run_bot_match
from gwent_engine.ai.baseline import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    get_base_profile_definition,
)
from gwent_engine.ai.debug import DecisionExplainer
from gwent_engine.ai.observations import PlayerObservation, build_player_observation
from gwent_engine.ai.search import (
    DEFAULT_SEARCH_CONFIG,
    SearchDecisionExplanation,
    build_search_engine,
)
from gwent_engine.cards import CardRegistry, DeckDefinition
from gwent_engine.cli.card_metadata import build_card_metadata_maps
from gwent_engine.cli.models import BotDecisionExplanation, CliMetadata, CliRun, CliStep
from gwent_engine.core import Zone
from gwent_engine.core.actions import GameAction
from gwent_engine.core.ids import DeckId, GameId, PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.scoring import calculate_effective_strength
from gwent_engine.runtime_assets import (
    load_card_registry,
    load_leader_registry,
    load_sample_deck_map,
    load_sample_decks,
)

DEFAULT_PLAYER_ONE_DECK_ID_STR = "monsters_hs_373"
DEFAULT_PLAYER_TWO_DECK_ID_STR = "nilfgaard_optimised"


def available_sample_decks() -> tuple[DeckDefinition, ...]:
    return load_sample_decks()


def available_leaders() -> tuple[LeaderDefinition, ...]:
    return tuple(
        sorted(
            load_leader_registry(),
            key=lambda leader: (leader.faction.value, leader.name, str(leader.leader_id)),
        )
    )


def run_bot_match_cli(
    *,
    player_one_bot_spec: str,
    player_two_bot_spec: str,
    player_one_deck_id: str = DEFAULT_PLAYER_ONE_DECK_ID_STR,
    player_two_deck_id: str = DEFAULT_PLAYER_TWO_DECK_ID_STR,
    player_one_leader_id: str | None = None,
    player_two_leader_id: str | None = None,
    seed: int = 0,
    starting_player: str = "p1",
    include_bot_explanations: bool = False,
) -> CliRun:
    card_registry = load_card_registry()
    leader_registry = load_leader_registry()
    deck_by_id = load_sample_deck_map()
    if player_one_deck_id not in deck_by_id:
        raise ValueError(f"Unknown sample deck id: {player_one_deck_id!r}")
    if player_two_deck_id not in deck_by_id:
        raise ValueError(f"Unknown sample deck id: {player_two_deck_id!r}")
    player_one_deck = _override_deck_leader(
        deck_by_id[player_one_deck_id],
        leader_id=player_one_leader_id,
        leader_registry=leader_registry,
    )
    player_two_deck = _override_deck_leader(
        deck_by_id[player_two_deck_id],
        leader_id=player_two_leader_id,
        leader_registry=leader_registry,
    )
    player_one_bot = create_bot(
        player_one_bot_spec,
        bot_id="p1_bot",
        seed=seed + 1,
    )
    player_two_bot = create_bot(
        player_two_bot_spec,
        bot_id="p2_bot",
        seed=seed + 2,
    )
    match_run = run_bot_match(
        game_id=GameId(f"bot_match_{seed}"),
        player_one_bot=player_one_bot,
        player_two_bot=player_two_bot,
        player_one_deck=player_one_deck,
        player_two_deck=player_two_deck,
        starting_player=PlayerId(starting_player),
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=SeededRandom(seed),
    )
    state = match_run.final_state
    (
        card_names_by_instance_id,
        card_values_by_instance_id,
        card_kinds_by_instance_id,
        card_spy_by_instance_id,
        card_medic_by_instance_id,
        card_horn_by_instance_id,
        card_scorch_by_instance_id,
    ) = build_card_metadata_maps(state, card_registry=card_registry)
    final_strengths_by_instance_id = {
        card.instance_id: calculate_effective_strength(
            state,
            card_registry,
            card.instance_id,
            leader_registry=leader_registry,
        )
        for card in state.card_instances
        if card.zone == Zone.BATTLEFIELD
    }
    bot_specs = {
        PlayerId("p1"): player_one_bot_spec,
        PlayerId("p2"): player_two_bot_spec,
    }
    return CliRun(
        scenario_name="bot_match",
        metadata=CliMetadata(
            game_id=match_run.game_id,
            player_one_id=match_run.player_one_id,
            player_two_id=match_run.player_two_id,
            player_one_deck_id=DeckId(match_run.player_one_deck_id),
            player_two_deck_id=DeckId(match_run.player_two_deck_id),
            player_one_leader_id=player_one_deck.leader_id,
            player_two_leader_id=player_two_deck.leader_id,
            player_one_leader_name=leader_registry.get(player_one_deck.leader_id).name,
            player_two_leader_name=leader_registry.get(player_two_deck.leader_id).name,
            rng_name=match_run.rng_name,
            pending_choice_encountered=match_run.pending_choice_state is not None,
            player_one_actor=match_run.player_one_bot_name,
            player_two_actor=match_run.player_two_bot_name,
        ),
        steps=tuple(
            CliStep(
                action=step.action,
                events=step.events,
                state_before=step.state_before,
                state_after=step.state_after,
                bot_explanation=(
                    _bot_explanation_for_step(
                        step.state_before,
                        step.action,
                        bot_specs=bot_specs,
                        card_registry=card_registry,
                        leader_registry=leader_registry,
                    )
                    if include_bot_explanations
                    else None
                ),
                round_summary_state=step.round_summary_state,
                effective_strengths_before=step.effective_strengths_before,
                effective_strengths_after=step.effective_strengths_after,
                round_summary_strengths=step.round_summary_strengths,
            )
            for step in match_run.steps
        ),
        pending_choice_state=match_run.pending_choice_state,
        final_state=match_run.final_state,
        card_names_by_instance_id=card_names_by_instance_id,
        card_values_by_instance_id=card_values_by_instance_id,
        card_kinds_by_instance_id=card_kinds_by_instance_id,
        card_spy_by_instance_id=card_spy_by_instance_id,
        card_medic_by_instance_id=card_medic_by_instance_id,
        card_horn_by_instance_id=card_horn_by_instance_id,
        card_scorch_by_instance_id=card_scorch_by_instance_id,
        final_strengths_by_instance_id=final_strengths_by_instance_id,
    )


def _override_deck_leader(
    deck: DeckDefinition,
    *,
    leader_id: str | None,
    leader_registry: LeaderRegistry,
) -> DeckDefinition:
    if leader_id is None or leader_id == str(deck.leader_id):
        return deck
    overridden_leader_id = type(deck.leader_id)(leader_id)
    leader_definition = leader_registry.get(overridden_leader_id)
    if leader_definition.faction != deck.faction:
        message = (
            f"Leader {leader_id!r} belongs to faction {leader_definition.faction!r}, "
            + f"expected {deck.faction!r} for deck {deck.deck_id!r}."
        )
        raise ValueError(message)
    return type(deck)(
        deck_id=deck.deck_id,
        faction=deck.faction,
        leader_id=overridden_leader_id,
        card_definition_ids=deck.card_definition_ids,
    )


def _bot_explanation_for_step(
    state_before: GameState,
    action: GameAction,
    *,
    bot_specs: dict[PlayerId, str],
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> BotDecisionExplanation | None:
    raw_player_id = getattr(action, "player_id", None)
    if not isinstance(raw_player_id, str):
        return None
    player_id = cast(PlayerId, raw_player_id)
    raw_spec = bot_specs.get(player_id)
    if raw_spec is None:
        return None
    family, profile_id = parse_bot_spec(raw_spec)
    profile_definition = (
        get_base_profile_definition(profile_id) if profile_id is not None else DEFAULT_BASE_PROFILE
    )
    explainer = DecisionExplainer(
        card_registry=card_registry,
        leader_registry=leader_registry,
        profile_definition=profile_definition,
    )
    observation = build_player_observation(state_before, player_id, leader_registry)
    legal_actions = enumerate_legal_actions(
        state_before,
        player_id=player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=SeededRandom(0),
    )
    explainers: dict[str, Callable[[], BotDecisionExplanation]] = {
        "heuristic": lambda: explainer.explain_heuristic_from_state(
            state_before,
            player_id=player_id,
        ),
        "search": lambda: _search_explanation(
            observation=observation,
            legal_actions=legal_actions,
            profile_definition=profile_definition,
            player_id=player_id,
            state_before=state_before,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ),
    }
    explain = explainers.get(family)
    if explain is None:
        return None
    return explain()


def _search_explanation(
    *,
    observation: PlayerObservation,
    legal_actions: tuple[GameAction, ...],
    profile_definition: BaseProfileDefinition,
    player_id: PlayerId,
    state_before: GameState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> SearchDecisionExplanation:
    search_engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=profile_definition,
        bot_id=f"{player_id}_search_explainer",
    )
    result = (
        search_engine.choose_pending_choice(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        if state_before.pending_choice is not None
        and state_before.pending_choice.player_id == player_id
        else search_engine.choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    )
    return search_engine.explain_result(result)
