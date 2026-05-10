from dataclasses import replace
from pathlib import Path

from gwent_engine.ai.action_legality import is_legal_action
from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.cards.loaders import load_card_definitions
from gwent_engine.cards.models import DeckDefinition
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import (
    CardType,
    FactionId,
    GameStatus,
    LeaderAbilityKind,
    Phase,
    Row,
)
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.events import GameEvent
from gwent_engine.core.ids import (
    CardInstanceId,
    DeckId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    PendingChoice,
    RowState,
)
from gwent_engine.decks import load_sample_decks
from gwent_engine.leaders.loaders import load_leader_definitions
from gwent_engine.leaders.registry import LeaderRegistry
from gwent_engine.rules.game_setup import PlayerDeck, build_game_state

from tests.engine.primitives import (
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    battlefield_card,
    make_card_instance,
    weather_card,
)
from tests.engine.scenario_builder import ScenarioCard, ScenarioRows, card, rows, scenario
from tests.support import IdentityShuffle, IndexedRandom

__all__ = (
    "CARD_REGISTRY",
    "DEFAULT_PLAYER_ONE_DECK_ID",
    "DEFAULT_PLAYER_TWO_DECK_ID",
    "LEADER_REGISTRY",
    "MONSTERS_ANY_WEATHER_LEADER_ID",
    "MONSTERS_CLOSE_HORN_LEADER_ID",
    "MONSTERS_DECK_ID",
    "MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID",
    "MONSTERS_DOUBLE_SPY_LEADER_ID",
    "MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID",
    "NILFGAARD_DECK_ID",
    "NILFGAARD_RAIN_FROM_DECK_LEADER_ID",
    "NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID",
    "NILFGAARD_RELENTLESS_LEADER_ID",
    "NILFGAARD_REVEAL_HAND_LEADER_ID",
    "NILFGAARD_WHITE_FLAME_LEADER_ID",
    "NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID",
    "NORTHERN_REALMS_DECK_ID",
    "NORTHERN_REALMS_RANGED_SCORCH_LEADER_ID",
    "NORTHERN_REALMS_SIEGE_HORN_LEADER_ID",
    "NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID",
    "PLAYER_ONE_ID",
    "PLAYER_TWO_ID",
    "SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID",
    "SCOIATAEL_CLOSE_SCORCH_LEADER_ID",
    "SCOIATAEL_DAISY_OF_THE_VALLEY_LEADER_ID",
    "SCOIATAEL_DECK_ID",
    "SCOIATAEL_FROST_FROM_DECK_LEADER_ID",
    "SCOIATAEL_LEADER_PASSIVES_DECK_ID",
    "SCOIATAEL_RANGED_HORN_LEADER_ID",
    "SKELLIGE_KING_BRAN_LEADER_ID",
    "SKELLIGE_SHUFFLE_DISCARDS_LEADER_ID",
    "SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID",
    "IdentityShuffle",
    "IndexedRandom",
    "battlefield_card",
    "first_hand_unit_for_row",
    "make_card_instance",
    "sample_deck_id_for",
    "weather_card",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
EMPTY_ROWS = RowState()

MONSTERS_CLOSE_HORN_LEADER_ID = LeaderId("monsters_eredin_commander_of_the_red_riders")
MONSTERS_ANY_WEATHER_LEADER_ID = LeaderId("monsters_eredin_king_of_the_wild_hunt")
MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID = LeaderId("monsters_eredin_destroyer_of_worlds")
MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID = LeaderId("monsters_eredin_bringer_of_death")
MONSTERS_DOUBLE_SPY_LEADER_ID = LeaderId("monsters_eredin_breacc_glas_the_treacherous")
NILFGAARD_RAIN_FROM_DECK_LEADER_ID = LeaderId("nilfgaard_emhyr_his_imperial_majesty")
NILFGAARD_REVEAL_HAND_LEADER_ID = LeaderId("nilfgaard_emhyr_emperor_of_nilfgaard")
NILFGAARD_WHITE_FLAME_LEADER_ID = LeaderId("nilfgaard_emhyr_the_white_flame")
NILFGAARD_RELENTLESS_LEADER_ID = LeaderId("nilfgaard_emhyr_the_relentless")
NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID = LeaderId("nilfgaard_emhyr_invader_of_the_north")
NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID = LeaderId(
    "northern_realms_foltest_lord_commander_of_the_north"
)
NORTHERN_REALMS_SIEGE_HORN_LEADER_ID = LeaderId("northern_realms_foltest_the_siegemaster")
NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID = LeaderId("northern_realms_foltest_the_steel_forged")
NORTHERN_REALMS_RANGED_SCORCH_LEADER_ID = LeaderId("northern_realms_foltest_son_of_medell")
SCOIATAEL_FROST_FROM_DECK_LEADER_ID = LeaderId("scoiatael_francesca_pureblood_elf")
SCOIATAEL_DAISY_OF_THE_VALLEY_LEADER_ID = LeaderId("scoiatael_francesca_daisy_of_the_valley")
SCOIATAEL_RANGED_HORN_LEADER_ID = LeaderId("scoiatael_francesca_the_beautiful")
SCOIATAEL_CLOSE_SCORCH_LEADER_ID = LeaderId("scoiatael_francesca_queen_of_dol_blathanna")
SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID = LeaderId("scoiatael_francesca_hope_of_the_aen_seidhe")
SKELLIGE_SHUFFLE_DISCARDS_LEADER_ID = LeaderId("skellige_crach_an_craite")
SKELLIGE_KING_BRAN_LEADER_ID = LeaderId("skellige_king_bran")

MONSTERS_DECK_ID = DeckId("monsters_muster_swarm_strict")
NILFGAARD_DECK_ID = DeckId("nilfgaard_spy_medic_control_strict")
NORTHERN_REALMS_DECK_ID = DeckId("northern_realms_spy_siege_bond_strict")
SCOIATAEL_DECK_ID = DeckId("scoiatael_high_stakes")
SCOIATAEL_LEADER_PASSIVES_DECK_ID = SCOIATAEL_DECK_ID
SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID = DeckId("skellige_cerys_berserker_combo_strict")
DEFAULT_PLAYER_ONE_DECK_ID = MONSTERS_DECK_ID
DEFAULT_PLAYER_TWO_DECK_ID = NILFGAARD_DECK_ID

_FACTION_DECK_IDS = {
    FactionId.MONSTERS: MONSTERS_DECK_ID,
    FactionId.NILFGAARD: NILFGAARD_DECK_ID,
    FactionId.NORTHERN_REALMS: NORTHERN_REALMS_DECK_ID,
    FactionId.SCOIATAEL: SCOIATAEL_DECK_ID,
    FactionId.SKELLIGE: SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
}


def build_sample_game_state(
    *,
    player_one_deck_id: DeckId = DEFAULT_PLAYER_ONE_DECK_ID,
    player_two_deck_id: DeckId = DEFAULT_PLAYER_TWO_DECK_ID,
) -> GameState:
    return build_game_state(
        game_id=GameId("game_1"),
        player_decks=(
            PlayerDeck(
                player_id=PLAYER_ONE_ID,
                deck=_deck_by_id(player_one_deck_id),
            ),
            PlayerDeck(
                player_id=PLAYER_TWO_ID,
                deck=_deck_by_id(player_two_deck_id),
            ),
        ),
    )


# Test registries are immutable and shared across the suite. Initialize them
# once at import time and use them directly in tests.
CARD_REGISTRY = CardRegistry.from_definitions(load_card_definitions(DATA_DIR / "cards.yaml"))
LEADER_REGISTRY = LeaderRegistry.from_definitions(
    load_leader_definitions(DATA_DIR / "leaders.yaml")
)
SAMPLE_DECKS = tuple(
    load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
)


def sample_deck_id_for(
    *,
    faction: FactionId | str,
    leader_ability_kind: LeaderAbilityKind | None = None,
    contains: tuple[str, ...] = (),
) -> DeckId:
    resolved_faction = FactionId(str(faction))
    if leader_ability_kind == LeaderAbilityKind.DRAW_EXTRA_OPENING_CARD:
        return SCOIATAEL_LEADER_PASSIVES_DECK_ID
    if "skellige_kambi" in contains:
        return SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID
    deck_id = _FACTION_DECK_IDS.get(resolved_faction)
    if deck_id is not None:
        return deck_id
    message = (
        f"No hardcoded test deck mapping for faction={resolved_faction!r}, "
        + f"leader_ability_kind={leader_ability_kind!r}, contains={contains!r}."
    )
    raise AssertionError(message)


def _deck_by_id(deck_id: DeckId) -> DeckDefinition:
    for deck in SAMPLE_DECKS:
        if deck.deck_id == deck_id:
            return deck
    raise AssertionError(f"Unknown sample deck id {deck_id!r}.")


def build_started_game_state(
    *,
    starting_player: PlayerId = PLAYER_ONE_ID,
    player_one_deck_id: DeckId = DEFAULT_PLAYER_ONE_DECK_ID,
    player_two_deck_id: DeckId = DEFAULT_PLAYER_TWO_DECK_ID,
) -> tuple[GameState, CardRegistry]:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    initial_state = build_sample_game_state(
        player_one_deck_id=player_one_deck_id,
        player_two_deck_id=player_two_deck_id,
    )
    started_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=starting_player),
        rng=IdentityShuffle(),
        leader_registry=leader_registry,
    )
    return started_state, card_registry


def build_in_round_game_state(
    *,
    starting_player: PlayerId = PLAYER_ONE_ID,
    player_one_deck_id: DeckId = DEFAULT_PLAYER_ONE_DECK_ID,
    player_two_deck_id: DeckId = DEFAULT_PLAYER_TWO_DECK_ID,
    player_one_mulligan_cards: tuple[CardInstanceId, ...] = (),
    player_two_mulligan_cards: tuple[CardInstanceId, ...] = (),
) -> tuple[GameState, CardRegistry]:
    started_state, card_registry = build_started_game_state(
        starting_player=starting_player,
        player_one_deck_id=player_one_deck_id,
        player_two_deck_id=player_two_deck_id,
    )
    in_round_state, _ = apply_action(
        started_state,
        ResolveMulligansAction(
            selections=(
                MulliganSelection(
                    player_id=PLAYER_ONE_ID,
                    cards_to_replace=player_one_mulligan_cards,
                ),
                MulliganSelection(
                    player_id=PLAYER_TWO_ID,
                    cards_to_replace=player_two_mulligan_cards,
                ),
            )
        ),
    )
    return in_round_state, card_registry


def first_hand_unit_for_row(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> CardInstanceId:
    for card_instance_id in state.player(player_id).hand:
        definition = card_registry.get(state.card(card_instance_id).definition_id)
        if definition.card_type == CardType.UNIT and row in definition.allowed_rows:
            return card_instance_id
    raise AssertionError(f"No unit in {player_id!r} hand can be played to {row!r}.")


def run_scripted_round() -> tuple[GameState, tuple[GameEvent, ...]]:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    state = build_sample_game_state(
        player_one_deck_id=NILFGAARD_DECK_ID,
        player_two_deck_id=NILFGAARD_DECK_ID,
    )
    rng = IdentityShuffle()
    events: list[GameEvent] = []
    state, action_events = apply_action(
        state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=rng,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    events.extend(action_events)
    state, action_events = apply_action(
        state,
        ResolveMulligansAction(
            selections=(
                MulliganSelection(player_id=PLAYER_ONE_ID, cards_to_replace=()),
                MulliganSelection(player_id=PLAYER_TWO_ID, cards_to_replace=()),
            )
        ),
        rng=rng,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    events.extend(action_events)
    for player_id, row in (
        (PLAYER_ONE_ID, Row.CLOSE),
        (PLAYER_TWO_ID, Row.RANGED),
        (PLAYER_ONE_ID, Row.CLOSE),
    ):
        state, action_events = _apply_first_legal_hand_play(
            state,
            player_id=player_id,
            target_row=row,
            rng=rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        events.extend(action_events)
    for action in (
        PassAction(player_id=PLAYER_TWO_ID),
        PassAction(player_id=PLAYER_ONE_ID),
    ):
        state, action_events = apply_action(
            state,
            action,
            rng=rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        events.extend(action_events)
    return state, tuple(events)


def _apply_first_legal_hand_play(
    state: GameState,
    *,
    player_id: PlayerId,
    target_row: Row,
    rng: SupportsRandom,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    for card_instance_id in state.player(player_id).hand:
        action = PlayCardAction(
            player_id=player_id,
            card_instance_id=card_instance_id,
            target_row=target_row,
        )
        if is_legal_action(
            state,
            action,
            rng=rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        ):
            return apply_action(
                state,
                action,
                rng=rng,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
    raise AssertionError(f"No legal hand card for {player_id!r} on row {target_row!r}.")


def legal_actions_for(
    state: GameState,
    *,
    player_id: PlayerId,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
    rng: SupportsRandom | None = None,
) -> tuple[GameAction, ...]:
    resolved_card_registry = card_registry or CARD_REGISTRY
    return enumerate_legal_actions(
        state,
        player_id=player_id,
        card_registry=resolved_card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def choose_bot_response(
    bot: BotAgent,
    state: GameState,
    *,
    player_id: PlayerId,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
    rng: SupportsRandom | None = None,
    pending_choice: bool = False,
) -> GameAction:
    resolved_card_registry = card_registry or CARD_REGISTRY
    legal_actions = legal_actions_for(
        state,
        player_id=player_id,
        card_registry=resolved_card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )
    observation = build_player_observation(state, player_id, leader_registry)
    if pending_choice:
        return bot.choose_pending_choice(
            observation,
            legal_actions,
            card_registry=resolved_card_registry,
            leader_registry=leader_registry,
        )
    return bot.choose_action(
        observation,
        legal_actions,
        card_registry=resolved_card_registry,
        leader_registry=leader_registry,
    )


## TODO: Should this use the scenario builder?
def build_custom_in_round_state(
    *,
    card_instances: tuple[CardInstance, ...],
    player_one_deck: tuple[CardInstanceId, ...] = (),
    player_one_hand: tuple[CardInstanceId, ...] = (),
    player_one_discard: tuple[CardInstanceId, ...] = (),
    player_one_rows: RowState = EMPTY_ROWS,
    player_two_deck: tuple[CardInstanceId, ...] = (),
    player_two_hand: tuple[CardInstanceId, ...] = (),
    player_two_discard: tuple[CardInstanceId, ...] = (),
    player_two_rows: RowState = EMPTY_ROWS,
    player_one_faction: FactionId = FactionId.SCOIATAEL,
    player_two_faction: FactionId = FactionId.SCOIATAEL,
    player_one_leader_id: LeaderId | None = None,
    player_two_leader_id: LeaderId | None = None,
    current_player: PlayerId = PLAYER_ONE_ID,
    starting_player: PlayerId = PLAYER_ONE_ID,
    round_starter: PlayerId = PLAYER_ONE_ID,
    weather: RowState = EMPTY_ROWS,
    pending_choice: PendingChoice | None = None,
) -> GameState:
    """Compatibility adapter that routes legacy test setup through the shared scenario DSL."""
    cards_by_id = {card_instance.instance_id: card_instance for card_instance in card_instances}

    def scenario_cards(card_ids: tuple[CardInstanceId, ...]) -> tuple[ScenarioCard, ...]:
        return tuple(
            card(
                instance_id=card_id,
                definition_id=str(cards_by_id[card_id].definition_id),
                owner=cards_by_id[card_id].owner,
            )
            for card_id in card_ids
        )

    def scenario_rows(row_state: RowState) -> ScenarioRows:
        return rows(
            close=scenario_cards(row_state.close),
            ranged=scenario_cards(row_state.ranged),
            siege=scenario_cards(row_state.siege),
        )

    built_state = (
        scenario("custom_in_round_game")
        .round(1)
        .phase(Phase.IN_ROUND)
        .status(GameStatus.IN_PROGRESS)
        .current_player(current_player)
        .turn_order(starting_player=starting_player, round_starter=round_starter)
        .player(
            PLAYER_ONE_ID,
            faction=player_one_faction,
            leader_id=player_one_leader_id or SCOIATAEL_RANGED_HORN_LEADER_ID,
            hand=scenario_cards(player_one_hand),
            deck=scenario_cards(player_one_deck),
            discard=scenario_cards(player_one_discard),
            board=scenario_rows(player_one_rows),
        )
        .player(
            PLAYER_TWO_ID,
            faction=player_two_faction,
            leader_id=player_two_leader_id or SCOIATAEL_RANGED_HORN_LEADER_ID,
            hand=scenario_cards(player_two_hand),
            deck=scenario_cards(player_two_deck),
            discard=scenario_cards(player_two_discard),
            board=scenario_rows(player_two_rows),
        )
        .weather(scenario_rows(weather))
        .build()
    )
    return replace(
        built_state,
        card_instances=card_instances,
        pending_choice=pending_choice,
    )
