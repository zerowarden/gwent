from gwent_engine.cards.models import CardDefinition, DeckDefinition
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import (
    AbilityKind,
    CardType,
    FactionId,
    LeaderAbilityKind,
    LeaderAbilityMode,
    Phase,
    Row,
)
from gwent_engine.core.actions import StartGameAction
from gwent_engine.core.ids import CardDefinitionId, DeckId, GameId, LeaderId, PlayerId
from gwent_engine.core.reducer import apply_action
from gwent_engine.decks.validation import (
    DEFAULT_DECK_RULESET,
    DeckRuleset,
    validate_deck,
)
from gwent_engine.leaders.models import LeaderDefinition
from gwent_engine.leaders.registry import LeaderRegistry
from gwent_engine.rules.game_setup import PlayerDeck, build_game_state

from tests.engine.support import (
    IdentityShuffle,
)


def _unit_definition(
    definition_id: str,
    *,
    faction: FactionId = FactionId.NORTHERN_REALMS,
    max_copies_per_deck: int | None = None,
) -> CardDefinition:
    return CardDefinition(
        definition_id=CardDefinitionId(definition_id),
        name=definition_id.replace("_", " ").title(),
        faction=faction,
        card_type=CardType.UNIT,
        base_strength=4,
        allowed_rows=(Row.CLOSE,),
        max_copies_per_deck=max_copies_per_deck,
    )


def _special_definition(
    definition_id: str,
    *,
    faction: FactionId = FactionId.NEUTRAL,
    ability_kind: AbilityKind = AbilityKind.CLEAR_WEATHER,
    max_copies_per_deck: int | None = None,
) -> CardDefinition:
    return CardDefinition(
        definition_id=CardDefinitionId(definition_id),
        name=definition_id.replace("_", " ").title(),
        faction=faction,
        card_type=CardType.SPECIAL,
        base_strength=0,
        allowed_rows=(),
        ability_kinds=(ability_kind,),
        max_copies_per_deck=max_copies_per_deck,
    )


def _leader_card_definition(
    definition_id: str,
    *,
    faction: FactionId = FactionId.NORTHERN_REALMS,
) -> CardDefinition:
    return CardDefinition(
        definition_id=CardDefinitionId(definition_id),
        name=definition_id.replace("_", " ").title(),
        faction=faction,
        card_type=CardType.LEADER,
        base_strength=0,
        allowed_rows=(),
    )


def _leader_definition(
    leader_id: str,
    *,
    faction: FactionId = FactionId.NORTHERN_REALMS,
) -> LeaderDefinition:
    return LeaderDefinition(
        leader_id=LeaderId(leader_id),
        name=leader_id.replace("_", " ").title(),
        faction=faction,
        ability_kind=LeaderAbilityKind.CLEAR_WEATHER,
        ability_mode=LeaderAbilityMode.ACTIVE,
    )


def _build_test_registries() -> tuple[CardRegistry, LeaderRegistry]:
    card_registry = CardRegistry.from_definitions(
        (
            _unit_definition("northern_test_infantry", max_copies_per_deck=30),
            _unit_definition("monsters_test_brute", faction=FactionId.MONSTERS),
            _unit_definition(
                "neutral_test_mercenary",
                faction=FactionId.NEUTRAL,
                max_copies_per_deck=30,
            ),
            _special_definition("neutral_test_weather", max_copies_per_deck=12),
            _leader_card_definition("northern_test_leader_card"),
            _unit_definition("northern_test_copy_limit_two", max_copies_per_deck=2),
            _unit_definition("northern_test_copy_limit_three", max_copies_per_deck=3),
            _unit_definition("northern_test_singleton"),
        )
    )
    leader_registry = LeaderRegistry.from_definitions(
        (
            _leader_definition("northern_test_leader"),
            _leader_definition("monsters_test_leader", faction=FactionId.MONSTERS),
        )
    )
    return card_registry, leader_registry


def _deck(
    *,
    deck_id: str = "test_deck",
    faction: FactionId = FactionId.NORTHERN_REALMS,
    leader_id: str = "northern_test_leader",
    card_definition_ids: tuple[str, ...],
) -> DeckDefinition:
    return DeckDefinition(
        deck_id=DeckId(deck_id),
        faction=faction,
        leader_id=LeaderId(leader_id),
        card_definition_ids=tuple(CardDefinitionId(card_id) for card_id in card_definition_ids),
    )


def test_valid_deck_passes() -> None:
    card_registry, leader_registry = _build_test_registries()
    valid_deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 22 + ("neutral_test_weather",) * 2,
    )

    result = validate_deck(valid_deck, card_registry, leader_registry)

    assert result.errors == ()


def test_deck_with_no_leader_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        leader_id="",
        card_definition_ids=("northern_test_infantry",) * 22,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["missing_leader"]


def test_deck_with_multiple_leaders_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 22 + ("northern_test_leader_card",),
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["multiple_leaders"]


def test_deck_with_fewer_than_twenty_two_unit_cards_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 21,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["too_few_unit_cards"]


def test_deck_with_more_than_ten_special_cards_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 22 + ("neutral_test_weather",) * 11,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["too_many_special_cards"]


def test_unknown_leader_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        leader_id="unknown_test_leader",
        card_definition_ids=("northern_test_infantry",) * 22,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["unknown_leader"]


def test_unknown_card_definition_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 21 + ("unknown_test_card",),
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert {error.code for error in result.errors} == {
        "unknown_card_definition",
        "too_few_unit_cards",
    }


def test_deck_faction_not_matching_leader_faction_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        faction=FactionId.MONSTERS,
        card_definition_ids=("neutral_test_mercenary",) * 22,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["leader_faction_mismatch"]


def test_off_faction_non_neutral_card_fails() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 21 + ("monsters_test_brute",),
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["card_faction_mismatch"]


def test_neutral_cards_are_allowed_when_faction_enforcement_is_on() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 21 + ("neutral_test_mercenary",),
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert result.errors == ()


def test_validation_returns_multiple_errors_when_applicable() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        leader_id="",
        card_definition_ids=("neutral_test_weather",) * 11 + ("unknown_test_card",),
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert {error.code for error in result.errors} == {
        "missing_leader",
        "too_few_unit_cards",
        "too_many_special_cards",
        "unknown_card_definition",
    }


def test_card_with_explicit_limit_two_passes_at_exact_limit() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 20
        + ("northern_test_copy_limit_two",) * 2,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert result.errors == ()


def test_card_with_explicit_limit_two_fails_above_limit() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 19
        + ("northern_test_copy_limit_two",) * 3,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["too_many_copies"]
    assert "northern_test_copy_limit_two" in result.errors[0].message
    assert "appears 3 times but limit is 2" in result.errors[0].message


def test_card_with_explicit_limit_three_passes_at_exact_limit() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 19
        + ("northern_test_copy_limit_three",) * 3,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert result.errors == ()


def test_card_with_explicit_limit_three_fails_above_limit() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 18
        + ("northern_test_copy_limit_three",) * 4,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["too_many_copies"]
    assert "northern_test_copy_limit_three" in result.errors[0].message
    assert "appears 4 times but limit is 3" in result.errors[0].message


def test_card_without_explicit_limit_defaults_to_single_copy() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 21 + ("northern_test_singleton",),
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert result.errors == ()


def test_card_without_explicit_limit_fails_when_duplicated() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 20 + ("northern_test_singleton",) * 2,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == ["too_many_copies"]
    assert "northern_test_singleton" in result.errors[0].message
    assert "appears 2 times but limit is 1" in result.errors[0].message


def test_multiple_copy_limit_violations_are_all_reported() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 16
        + ("northern_test_copy_limit_two",) * 3
        + ("northern_test_copy_limit_three",) * 4
        + ("northern_test_singleton",) * 2,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert [error.code for error in result.errors] == [
        "too_many_copies",
        "too_many_copies",
        "too_many_copies",
    ]
    assert "northern_test_copy_limit_two" in result.errors[0].message
    assert "northern_test_copy_limit_three" in result.errors[1].message
    assert "northern_test_singleton" in result.errors[2].message


def test_copy_limit_validation_coexists_with_other_deck_validation_rules() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("neutral_test_weather",) * 11 + ("northern_test_singleton",) * 2,
    )

    result = validate_deck(deck, card_registry, leader_registry)

    assert {error.code for error in result.errors} == {
        "too_few_unit_cards",
        "too_many_special_cards",
        "too_many_copies",
    }


def test_validation_can_be_configured_with_a_custom_ruleset() -> None:
    card_registry, leader_registry = _build_test_registries()
    deck = _deck(
        card_definition_ids=("northern_test_infantry",) * 10 + ("neutral_test_weather",) * 2,
    )

    result = validate_deck(
        deck,
        card_registry,
        leader_registry,
        ruleset=DeckRuleset(min_unit_cards=10, max_special_cards=2),
    )

    assert result.errors == ()


def test_deck_validation_is_not_wired_into_apply_action() -> None:
    card_registry, leader_registry = _build_test_registries()
    invalid_but_playable_deck = _deck(
        deck_id="invalid_but_playable_deck",
        card_definition_ids=("northern_test_infantry",) * 21 + ("neutral_test_weather",) * 2,
    )
    validation_result = validate_deck(
        invalid_but_playable_deck,
        card_registry,
        leader_registry,
        ruleset=DEFAULT_DECK_RULESET,
    )
    initial_state = build_game_state(
        game_id=GameId("deck_validation_is_explicit"),
        player_decks=(
            PlayerDeck(player_id=PlayerId("p1"), deck=invalid_but_playable_deck),
            PlayerDeck(player_id=PlayerId("p2"), deck=invalid_but_playable_deck),
        ),
    )

    started_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p1")),
        rng=IdentityShuffle(),
    )

    assert validation_result.errors != ()
    assert started_state.phase == Phase.MULLIGAN
