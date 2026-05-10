from __future__ import annotations

from typing import final, override

from gwent_engine.cards import CardRegistry, DeckDefinition
from gwent_engine.cli.card_metadata import build_card_metadata_maps
from gwent_engine.cli.models import CliMetadata, CliRun, CliStep
from gwent_engine.cli.scenario_models import (
    CliScenario,
    ScenarioLeaveStep,
    ScenarioMulliganStep,
    ScenarioPassStep,
    ScenarioPlayCardStep,
    ScenarioPlayer,
    ScenarioResolveChoiceStep,
    ScenarioRng,
    ScenarioStartGameStep,
    ScenarioStep,
    ScenarioUseLeaderAbilityStep,
)
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.events import RoundEndedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.randomness import IdentityRandom, choose_by_index
from gwent_engine.core.reducer import apply_action_with_intermediate_state
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.game_setup import PlayerDeck, build_game_state
from gwent_engine.rules.scoring import battlefield_effective_strengths


@final
class ScenarioRandom(IdentityRandom):
    def __init__(self, config: ScenarioRng) -> None:
        self._choice_index = _scenario_choice_index(config)

    @override
    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return choose_by_index(cards, self._choice_index)


def _scenario_choice_index(config: ScenarioRng) -> int:
    if config.choice == "last":
        return -1
    if config.choice == "index":
        return config.choice_index
    return 0


def run_loaded_scenario(
    scenario: CliScenario,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> CliRun:
    alias_to_instance_id = _build_alias_map(scenario, card_registry=card_registry)
    player_decks = (
        PlayerDeck(
            player_id=scenario.players[0].player_id,
            deck=_build_deck_definition(scenario.players[0]),
        ),
        PlayerDeck(
            player_id=scenario.players[1].player_id,
            deck=_build_deck_definition(scenario.players[1]),
        ),
    )
    state = build_game_state(
        game_id=scenario.game_id,
        player_decks=player_decks,
        rng_seed=0,
    )
    (
        card_names_by_instance_id,
        card_values_by_instance_id,
        card_kinds_by_instance_id,
        card_spy_by_instance_id,
        card_medic_by_instance_id,
        card_horn_by_instance_id,
        card_scorch_by_instance_id,
    ) = build_card_metadata_maps(state, card_registry=card_registry)

    rng = ScenarioRandom(scenario.rng)
    steps: list[CliStep] = []
    pending_choice_state: GameState | None = None
    for step in scenario.steps:
        action = _action_from_step(step, state=state, alias_to_instance_id=alias_to_instance_id)
        state_before = state
        strengths_before = battlefield_effective_strengths(
            state_before,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        state, emitted_events, intermediate_state = apply_action_with_intermediate_state(
            state,
            action,
            rng=rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        round_summary_state = (
            intermediate_state
            if any(isinstance(event, RoundEndedEvent) for event in emitted_events)
            else None
        )
        steps.append(
            CliStep(
                action=action,
                events=emitted_events,
                state_before=state_before,
                state_after=state,
                bot_explanation=None,
                round_summary_state=round_summary_state,
                effective_strengths_before=strengths_before,
                effective_strengths_after=battlefield_effective_strengths(
                    state,
                    card_registry=card_registry,
                    leader_registry=leader_registry,
                ),
                round_summary_strengths=(
                    battlefield_effective_strengths(
                        round_summary_state,
                        card_registry=card_registry,
                        leader_registry=leader_registry,
                    )
                    if round_summary_state is not None
                    else {}
                ),
            )
        )
        if pending_choice_state is None and state.pending_choice is not None:
            pending_choice_state = state

    metadata = CliMetadata(
        game_id=scenario.game_id,
        player_one_id=player_decks[0].player_id,
        player_two_id=player_decks[1].player_id,
        player_one_deck_id=player_decks[0].deck.deck_id,
        player_two_deck_id=player_decks[1].deck.deck_id,
        player_one_leader_id=player_decks[0].deck.leader_id,
        player_two_leader_id=player_decks[1].deck.leader_id,
        player_one_leader_name=leader_registry.get(player_decks[0].deck.leader_id).name,
        player_two_leader_name=leader_registry.get(player_decks[1].deck.leader_id).name,
        rng_name=ScenarioRandom.__name__,
        pending_choice_encountered=pending_choice_state is not None,
    )
    final_strengths_by_instance_id = {
        **battlefield_effective_strengths(
            state,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    }
    return CliRun(
        scenario_name=scenario.scenario_id,
        metadata=metadata,
        steps=tuple(steps),
        pending_choice_state=pending_choice_state,
        final_state=state,
        card_names_by_instance_id=card_names_by_instance_id,
        card_values_by_instance_id=card_values_by_instance_id,
        card_kinds_by_instance_id=card_kinds_by_instance_id,
        card_spy_by_instance_id=card_spy_by_instance_id,
        card_medic_by_instance_id=card_medic_by_instance_id,
        card_horn_by_instance_id=card_horn_by_instance_id,
        card_scorch_by_instance_id=card_scorch_by_instance_id,
        final_strengths_by_instance_id=final_strengths_by_instance_id,
    )


def _build_deck_definition(player: ScenarioPlayer) -> DeckDefinition:
    return DeckDefinition(
        deck_id=player.deck_id,
        faction=player.faction,
        leader_id=player.leader_id,
        card_definition_ids=tuple(entry.card_definition_id for entry in player.deck_entries),
    )


def _build_alias_map(
    scenario: CliScenario,
    *,
    card_registry: CardRegistry,
) -> dict[str, CardInstanceId]:
    alias_to_instance_id: dict[str, CardInstanceId] = {}
    for player in scenario.players:
        for index, entry in enumerate(player.deck_entries, start=1):
            _ = card_registry.get(entry.card_definition_id)
            alias_to_instance_id[entry.alias] = CardInstanceId(f"{player.player_id}_card_{index}")
    return alias_to_instance_id


def _action_from_step(
    step: ScenarioStep,
    *,
    state: GameState,
    alias_to_instance_id: dict[str, CardInstanceId],
) -> GameAction:
    action: GameAction
    match step:
        case ScenarioStartGameStep(starting_player=starting_player):
            assert starting_player is not None
            action = StartGameAction(starting_player=starting_player)
        case ScenarioMulliganStep(selections=selections):
            action = ResolveMulligansAction(
                selections=tuple(
                    MulliganSelection(
                        player_id=player.player_id,
                        cards_to_replace=tuple(
                            _resolve_card_ref(card_ref, alias_to_instance_id=alias_to_instance_id)
                            for card_ref in selections.get(player.player_id, ())
                        ),
                    )
                    for player in state.players
                )
            )
        case ScenarioPlayCardStep(
            player_id=player_id,
            card_ref=card_ref,
            target_row=target_row,
            target_card_ref=target_card_ref,
            secondary_target_card_ref=secondary_target_card_ref,
        ):
            action = PlayCardAction(
                player_id=player_id,
                card_instance_id=_resolve_card_ref(
                    card_ref,
                    alias_to_instance_id=alias_to_instance_id,
                ),
                target_row=target_row,
                target_card_instance_id=(
                    _resolve_card_ref(target_card_ref, alias_to_instance_id=alias_to_instance_id)
                    if target_card_ref is not None
                    else None
                ),
                secondary_target_card_instance_id=(
                    _resolve_card_ref(
                        secondary_target_card_ref,
                        alias_to_instance_id=alias_to_instance_id,
                    )
                    if secondary_target_card_ref is not None
                    else None
                ),
            )
        case ScenarioPassStep(player_id=player_id):
            action = PassAction(player_id=player_id)
        case ScenarioLeaveStep(player_id=player_id):
            action = LeaveAction(player_id=player_id)
        case ScenarioUseLeaderAbilityStep(
            player_id=player_id,
            target_row=target_row,
            target_player=target_player,
            target_card_ref=target_card_ref,
            secondary_target_card_ref=secondary_target_card_ref,
            selected_card_refs=selected_card_refs,
        ):
            action = UseLeaderAbilityAction(
                player_id=player_id,
                target_row=target_row,
                target_player=target_player,
                target_card_instance_id=(
                    _resolve_card_ref(target_card_ref, alias_to_instance_id=alias_to_instance_id)
                    if target_card_ref is not None
                    else None
                ),
                secondary_target_card_instance_id=(
                    _resolve_card_ref(
                        secondary_target_card_ref,
                        alias_to_instance_id=alias_to_instance_id,
                    )
                    if secondary_target_card_ref is not None
                    else None
                ),
                selected_card_instance_ids=tuple(
                    _resolve_card_ref(card_ref, alias_to_instance_id=alias_to_instance_id)
                    for card_ref in selected_card_refs
                ),
            )
        case ScenarioResolveChoiceStep(
            player_id=player_id,
            selected_card_refs=selected_card_refs,
            selected_rows=selected_rows,
        ):
            choice = state.pending_choice
            if choice is None:
                raise ValueError("Resolve choice step encountered with no pending choice in state.")
            action = ResolveChoiceAction(
                player_id=player_id,
                choice_id=choice.choice_id,
                selected_card_instance_ids=tuple(
                    _resolve_card_ref(card_ref, alias_to_instance_id=alias_to_instance_id)
                    for card_ref in selected_card_refs
                ),
                selected_rows=selected_rows,
            )
    return action


def _resolve_card_ref(
    card_ref: str,
    *,
    alias_to_instance_id: dict[str, CardInstanceId],
) -> CardInstanceId:
    return alias_to_instance_id.get(card_ref, CardInstanceId(card_ref))
