from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import questionary
from questionary import Choice

from gwent_engine.ai.baseline import available_base_profile_ids
from gwent_engine.cards import DeckDefinition
from gwent_engine.core.ids import PlayerId
from gwent_engine.leaders import LeaderDefinition


@dataclass(frozen=True, slots=True)
class BotMatchSelection:
    player_one_bot_spec: str
    player_two_bot_spec: str
    player_one_deck_id: str
    player_two_deck_id: str
    player_one_leader_id: str
    player_two_leader_id: str
    seed: int
    starting_player: str


def prompt_bot_match_selection(
    *,
    decks: tuple[DeckDefinition, ...],
    leaders: tuple[LeaderDefinition, ...],
) -> BotMatchSelection:
    player_one_bot_spec = _prompt_bot_spec(
        "Bot 1",
    )
    player_one_deck = _prompt_deck(
        "Bot 1 deck",
        decks,
    )
    player_one_leader = _prompt_leader(
        "Bot 1 leader",
        player_id=PlayerId("p1"),
        deck=player_one_deck,
        leaders=leaders,
    )

    player_two_bot_spec = _prompt_bot_spec(
        "Bot 2",
    )
    player_two_deck = _prompt_deck(
        "Bot 2 deck",
        decks,
    )
    player_two_leader = _prompt_leader(
        "Bot 2 leader",
        player_id=PlayerId("p2"),
        deck=player_two_deck,
        leaders=leaders,
    )

    return BotMatchSelection(
        player_one_bot_spec=player_one_bot_spec,
        player_two_bot_spec=player_two_bot_spec,
        player_one_deck_id=str(player_one_deck.deck_id),
        player_two_deck_id=str(player_two_deck.deck_id),
        player_one_leader_id=str(player_one_leader.leader_id),
        player_two_leader_id=str(player_two_leader.leader_id),
        seed=_prompt_seed(),
        starting_player=cast(
            str,
            _prompt_select(
                "Starting player",
                choices=(
                    Choice("Player 1", value="p1"),
                    Choice("Player 2", value="p2"),
                ),
            ),
        ),
    )


def _prompt_bot_spec(label: str) -> str:
    family = cast(
        str,
        _prompt_select(
            f"{label}",
            choices=(
                Choice("Random", value="random"),
                Choice("Greedy", value="greedy"),
                Choice("Heuristic", value="heuristic"),
                Choice("Search", value="search"),
            ),
        ),
    )
    if family not in {"heuristic", "search"}:
        return family
    profile_id = cast(
        str,
        _prompt_select(
            f"{label} profile",
            choices=tuple(
                Choice(
                    "Baseline" if profile == "baseline" else profile.replace("_", " ").title(),
                    value=profile,
                )
                for profile in available_base_profile_ids()
            ),
        ),
    )
    return family if profile_id == "baseline" else f"{family}:{profile_id}"


def _prompt_deck(
    label: str,
    decks: tuple[DeckDefinition, ...],
) -> DeckDefinition:
    return cast(
        DeckDefinition,
        _prompt_select(
            label,
            choices=tuple(
                Choice(
                    f"{deck.deck_id} [{deck.faction}]",
                    value=deck,
                )
                for deck in decks
            ),
        ),
    )


def _prompt_leader(
    label: str,
    *,
    player_id: PlayerId,
    deck: DeckDefinition,
    leaders: tuple[LeaderDefinition, ...],
) -> LeaderDefinition:
    matching_leaders = tuple(leader for leader in leaders if leader.faction == deck.faction)
    deck_leader = next(leader for leader in matching_leaders if leader.leader_id == deck.leader_id)
    ordered_leaders = (
        deck_leader,
        *tuple(leader for leader in matching_leaders if leader.leader_id != deck_leader.leader_id),
    )
    return cast(
        LeaderDefinition,
        _prompt_select(
            f"{label} ({player_id})",
            choices=tuple(
                Choice(
                    _leader_choice_label(leader, is_default=leader.leader_id == deck.leader_id),
                    value=leader,
                )
                for leader in ordered_leaders
            ),
        ),
    )


def _leader_choice_label(leader: LeaderDefinition, *, is_default: bool) -> str:
    suffix = " [deck default]" if is_default else ""
    return f"{leader.name} ({leader.leader_id}){suffix}"


def _prompt_seed() -> int:
    raw_value = _require_answer(
        cast(
            str | None,
            questionary.text(
                "Seed",
                default="0",
                validate=_validate_seed,
            ).ask(),
        ),
        label="seed",
    )
    return int(raw_value)


def _prompt_select(message: str, *, choices: tuple[Choice, ...]) -> object:
    return _require_answer(
        cast(object | None, questionary.select(message, choices=choices).ask()),
        label=message,
    )


def _validate_seed(text: str) -> bool | str:
    return text.isdigit() or "Seed must be a non-negative integer."


def _require_answer[T](value: T | None, *, label: str) -> T:
    if value is None:
        raise RuntimeError(f"Interactive selection cancelled while choosing {label}.")
    return value
