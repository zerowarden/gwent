from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from gwent_engine.cli.scenario_models import (
    CliScenario,
    ScenarioDeckEntry,
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
from gwent_engine.core import Row
from gwent_engine.core.errors import DefinitionLoadError
from gwent_engine.core.ids import CardDefinitionId, DeckId, GameId, LeaderId, PlayerId
from gwent_engine.core.yaml_parsing import (
    expect_mapping,
    expect_sequence,
    load_yaml_document,
    optional_int,
    optional_str,
    parse_enum,
    require_str,
)
from gwent_engine.leaders import LeaderRegistry

DEFAULT_SCENARIOS_DIR = Path(__file__).resolve().parents[5] / "data" / "scenarios"
EXPECTED_PLAYER_IDS: tuple[PlayerId, PlayerId] = (PlayerId("p1"), PlayerId("p2"))


def load_scenario_path(
    path: Path,
    *,
    leader_registry: LeaderRegistry,
    scenario_name: str | None = None,
) -> CliScenario:
    context = f"CLI scenario file {path}"
    document = expect_mapping(load_yaml_document(path), context=context)
    scenario_id = require_str(document, "id", context=context)
    if scenario_name is not None and scenario_id != scenario_name:
        raise DefinitionLoadError(
            f"{context} declares id {scenario_id!r}, expected {scenario_name!r}."
        )

    players = _load_players(
        expect_mapping(document.get("players"), context=f"{context} players"),
        leader_registry=leader_registry,
        context=context,
        scenario_id=scenario_id,
    )
    rng = _load_rng(document, context=context)
    starting_player = _load_player_id(
        optional_str(document, "starting_player", context=context) or "p1",
        context=context,
        field="starting_player",
    )
    steps = _load_steps(
        expect_sequence(document.get("steps"), context=f"{context} steps"),
        context=context,
        default_starting_player=starting_player,
    )

    return CliScenario(
        scenario_id=scenario_id,
        game_id=GameId(optional_str(document, "game_id", context=context) or scenario_id),
        starting_player=starting_player,
        rng=rng,
        players=players,
        steps=steps,
    )


def _load_players(
    players_mapping: Mapping[str, object],
    *,
    leader_registry: LeaderRegistry,
    context: str,
    scenario_id: str,
) -> tuple[ScenarioPlayer, ScenarioPlayer]:
    if set(players_mapping) != {"p1", "p2"}:
        raise DefinitionLoadError(f"{context} players must declare exactly 'p1' and 'p2'.")

    player_one = _load_player(
        player_id=EXPECTED_PLAYER_IDS[0],
        raw_player=expect_mapping(
            players_mapping[str(EXPECTED_PLAYER_IDS[0])],
            context=f"{context} {EXPECTED_PLAYER_IDS[0]}",
        ),
        leader_registry=leader_registry,
        context=context,
        scenario_id=scenario_id,
    )
    player_two = _load_player(
        player_id=EXPECTED_PLAYER_IDS[1],
        raw_player=expect_mapping(
            players_mapping[str(EXPECTED_PLAYER_IDS[1])],
            context=f"{context} {EXPECTED_PLAYER_IDS[1]}",
        ),
        leader_registry=leader_registry,
        context=context,
        scenario_id=scenario_id,
    )
    players = (player_one, player_two)
    _validate_unique_aliases(players, context=context)
    return players


def _load_player(
    *,
    player_id: PlayerId,
    raw_player: Mapping[str, object],
    leader_registry: LeaderRegistry,
    context: str,
    scenario_id: str,
) -> ScenarioPlayer:
    player_context = f"{context} player {player_id}"
    leader_id = LeaderId(require_str(raw_player, "leader_id", context=player_context))
    leader_definition = leader_registry.get(leader_id)
    deck_entries = _load_deck_entries(
        expect_sequence(raw_player.get("deck"), context=f"{player_context} deck"),
        context=player_context,
    )
    return ScenarioPlayer(
        player_id=player_id,
        deck_id=DeckId(
            optional_str(raw_player, "deck_id", context=player_context)
            or f"{scenario_id}_{player_id}_deck"
        ),
        faction=leader_definition.faction,
        leader_id=leader_definition.leader_id,
        deck_entries=deck_entries,
    )


def _load_deck_entries(
    raw_entries: object,
    *,
    context: str,
) -> tuple[ScenarioDeckEntry, ...]:
    deck_entries: list[ScenarioDeckEntry] = []
    for index, raw_entry in enumerate(expect_sequence(raw_entries, context=context), start=1):
        entry_context = f"{context} entry {index}"
        entry_mapping = expect_mapping(raw_entry, context=entry_context)
        alias = require_str(entry_mapping, "alias", context=entry_context)
        card_definition_id = CardDefinitionId(
            require_str(entry_mapping, "card_id", context=entry_context)
        )
        deck_entries.append(ScenarioDeckEntry(alias=alias, card_definition_id=card_definition_id))
    if not deck_entries:
        raise DefinitionLoadError(f"{context} must contain at least one card.")
    return tuple(deck_entries)


def _validate_unique_aliases(
    players: tuple[ScenarioPlayer, ScenarioPlayer],
    *,
    context: str,
) -> None:
    seen_aliases: set[str] = set()
    for player in players:
        for entry in player.deck_entries:
            if entry.alias in seen_aliases:
                raise DefinitionLoadError(
                    f"{context} alias {entry.alias!r} is declared more than once."
                )
            seen_aliases.add(entry.alias)


def _load_rng(mapping: Mapping[str, object], *, context: str) -> ScenarioRng:
    raw_rng = mapping.get("rng")
    if raw_rng is None:
        return ScenarioRng()
    rng_mapping = expect_mapping(raw_rng, context=f"{context} rng")
    shuffle = optional_str(rng_mapping, "shuffle", context=f"{context} rng") or "identity"
    choice = optional_str(rng_mapping, "choice", context=f"{context} rng") or "first"
    choice_index = optional_int(rng_mapping, "choice_index", context=f"{context} rng") or 0
    if shuffle != "identity":
        raise DefinitionLoadError(f"{context} rng shuffle mode {shuffle!r} is unsupported.")
    if choice not in {"first", "last", "index"}:
        raise DefinitionLoadError(f"{context} rng choice mode {choice!r} is unsupported.")
    if choice != "index" and "choice_index" in rng_mapping:
        raise DefinitionLoadError(
            f"{context} rng choice_index is only valid when choice is 'index'."
        )
    return ScenarioRng(shuffle=shuffle, choice=choice, choice_index=choice_index)


def _load_steps(
    raw_steps: object,
    *,
    context: str,
    default_starting_player: PlayerId,
) -> tuple[ScenarioStep, ...]:
    steps: list[ScenarioStep] = []
    for index, raw_step in enumerate(
        expect_sequence(raw_steps, context=f"{context} steps"),
        start=1,
    ):
        step_context = f"{context} step {index}"
        step_mapping = expect_mapping(raw_step, context=step_context)
        step_type = require_str(step_mapping, "type", context=step_context)
        steps.append(
            _load_step(
                step_type=step_type,
                step_mapping=step_mapping,
                context=step_context,
                default_starting_player=default_starting_player,
            )
        )
    if not steps:
        raise DefinitionLoadError(f"{context} must declare at least one step.")
    return tuple(steps)


def _load_step(
    *,
    step_type: str,
    step_mapping: Mapping[str, object],
    context: str,
    default_starting_player: PlayerId,
) -> ScenarioStep:
    step: ScenarioStep
    match step_type:
        case "start_game":
            step = _load_start_game_step(
                step_mapping,
                context=context,
                default_starting_player=default_starting_player,
            )
        case "mulligan":
            step = _load_mulligan_step(step_mapping, context=context)
        case "play_card":
            step = _load_play_card_step(step_mapping, context=context)
        case "pass":
            step = ScenarioPassStep(player_id=_require_player_id(step_mapping, context=context))
        case "leave":
            step = ScenarioLeaveStep(player_id=_require_player_id(step_mapping, context=context))
        case "use_leader":
            step = _load_use_leader_step(step_mapping, context=context)
        case "resolve_choice":
            step = _load_resolve_choice_step(step_mapping, context=context)
        case _:
            raise DefinitionLoadError(f"{context} has unsupported step type {step_type!r}.")
    return step


def _load_start_game_step(
    step_mapping: Mapping[str, object],
    *,
    context: str,
    default_starting_player: PlayerId,
) -> ScenarioStartGameStep:
    starting_player = optional_str(step_mapping, "starting_player", context=context)
    return ScenarioStartGameStep(
        starting_player=(
            _load_player_id(starting_player, context=context, field="starting_player")
            if starting_player is not None
            else default_starting_player
        )
    )


def _load_mulligan_step(
    step_mapping: Mapping[str, object],
    *,
    context: str,
) -> ScenarioMulliganStep:
    raw_selections = expect_mapping(
        step_mapping.get("selections"),
        context=f"{context} selections",
    )
    selections = {
        player_id: tuple(
            str(alias)
            for alias in expect_sequence(
                raw_selections.get(str(player_id), []),
                context=f"{context} selections {player_id}",
            )
        )
        for player_id in EXPECTED_PLAYER_IDS
    }
    return ScenarioMulliganStep(selections=selections)


def _load_play_card_step(
    step_mapping: Mapping[str, object],
    *,
    context: str,
) -> ScenarioPlayCardStep:
    return ScenarioPlayCardStep(
        player_id=_require_player_id(step_mapping, context=context),
        card_ref=require_str(step_mapping, "card", context=context),
        target_row=_optional_row(step_mapping, "row", context=context),
        target_card_ref=optional_str(step_mapping, "target_card", context=context),
        secondary_target_card_ref=optional_str(
            step_mapping,
            "secondary_target_card",
            context=context,
        ),
    )


def _load_use_leader_step(
    step_mapping: Mapping[str, object],
    *,
    context: str,
) -> ScenarioUseLeaderAbilityStep:
    target_player = optional_str(step_mapping, "target_player", context=context)
    return ScenarioUseLeaderAbilityStep(
        player_id=_require_player_id(step_mapping, context=context),
        target_row=_optional_row(step_mapping, "row", context=context),
        target_player=(
            _load_player_id(target_player, context=context, field="target_player")
            if target_player is not None
            else None
        ),
        target_card_ref=optional_str(step_mapping, "target_card", context=context),
        secondary_target_card_ref=optional_str(
            step_mapping,
            "secondary_target_card",
            context=context,
        ),
        selected_card_refs=_load_selected_card_refs(step_mapping, context=context),
    )


def _load_resolve_choice_step(
    step_mapping: Mapping[str, object],
    *,
    context: str,
) -> ScenarioResolveChoiceStep:
    return ScenarioResolveChoiceStep(
        player_id=_require_player_id(step_mapping, context=context),
        selected_card_refs=_load_selected_card_refs(step_mapping, context=context),
        selected_rows=tuple(
            _load_row(str(item), context=f"{context} selected_rows")
            for item in expect_sequence(
                step_mapping.get("selected_rows", []),
                context=f"{context} selected_rows",
            )
        ),
    )


def _require_player_id(
    step_mapping: Mapping[str, object],
    *,
    context: str,
) -> PlayerId:
    return _load_player_id(
        require_str(step_mapping, "player", context=context),
        context=context,
        field="player",
    )


def _load_selected_card_refs(
    step_mapping: Mapping[str, object],
    *,
    context: str,
) -> tuple[str, ...]:
    return tuple(
        str(item)
        for item in expect_sequence(
            step_mapping.get("selected_cards", []),
            context=f"{context} selected_cards",
        )
    )


def _optional_row(mapping: Mapping[str, object], field: str, *, context: str) -> Row | None:
    row_name = optional_str(mapping, field, context=context)
    if row_name is None:
        return None
    return _load_row(row_name, context=f"{context} {field}")


def _load_row(value: str, *, context: str) -> Row:
    return parse_enum(
        Row,
        value,
        error_factory=lambda raw_value: DefinitionLoadError(
            f"{context} row {raw_value!r} is unknown."
        ),
    )


def _load_player_id(value: str | None, *, context: str, field: str) -> PlayerId:
    if value is None:
        raise DefinitionLoadError(f"{context} field {field!r} is required.")
    player_id = PlayerId(value)
    if player_id not in EXPECTED_PLAYER_IDS:
        raise DefinitionLoadError(f"{context} field {field!r} must be 'p1' or 'p2'.")
    return player_id
