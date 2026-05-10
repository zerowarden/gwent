from enum import StrEnum


class Row(StrEnum):
    CLOSE = "close"
    RANGED = "ranged"
    SIEGE = "siege"


class Zone(StrEnum):
    DECK = "deck"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    WEATHER = "weather"
    DISCARD = "discard"


class Phase(StrEnum):
    NOT_STARTED = "not_started"
    MULLIGAN = "mulligan"
    IN_ROUND = "in_round"
    ROUND_RESOLUTION = "round_resolution"
    MATCH_ENDED = "match_ended"


class GameStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    MATCH_ENDED = "match_ended"


class FactionId(StrEnum):
    MONSTERS = "monsters"
    NEUTRAL = "neutral"
    NILFGAARD = "nilfgaard"
    NORTHERN_REALMS = "northern_realms"
    SCOIATAEL = "scoiatael"
    SKELLIGE = "skellige"


class PassiveKind(StrEnum):
    MONSTERS_KEEP_ONE_UNIT = "monsters_keep_one_unit"
    NILFGAARD_WINS_TIES = "nilfgaard_wins_ties"
    NORTHERN_REALMS_DRAW_ON_ROUND_WIN = "northern_realms_draw_on_round_win"
    SCOIATAEL_CHOOSES_STARTING_PLAYER = "scoiatael_chooses_starting_player"
    SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE = (
        "skellige_summon_two_from_discard_on_round_three"
    )


class CardType(StrEnum):
    UNIT = "unit"
    SPECIAL = "special"
    LEADER = "leader"


class AbilityKind(StrEnum):
    BITING_FROST = "biting_frost"
    IMPENETRABLE_FOG = "impenetrable_fog"
    TORRENTIAL_RAIN = "torrential_rain"
    SKELLIGE_STORM = "skellige_storm"
    CLEAR_WEATHER = "clear_weather"
    COMMANDERS_HORN = "commanders_horn"
    SCORCH = "scorch"
    DECOY = "decoy"
    AGILE = "agile"
    MEDIC = "medic"
    MUSTER = "muster"
    MORALE_BOOST = "morale_boost"
    TIGHT_BOND = "tight_bond"
    SPY = "spy"
    UNIT_COMMANDERS_HORN = "unit_commanders_horn"
    UNIT_SCORCH_ROW = "unit_scorch_row"
    BERSERKER = "berserker"
    MARDROEME = "mardroeme"
    AVENGER = "avenger"


class ChoiceKind(StrEnum):
    SELECT_CARD_INSTANCE = "select_card_instance"


class ChoiceSourceKind(StrEnum):
    DECOY = "decoy"
    MEDIC = "medic"
    LEADER_ABILITY = "leader_ability"


class EffectSourceCategory(StrEnum):
    SPECIAL_CARD = "special_card"
    UNIT_ABILITY = "unit_ability"
    LEADER_ABILITY = "leader_ability"


class LeaderAbilityMode(StrEnum):
    ACTIVE = "active"
    PASSIVE = "passive"


class LeaderSelectionMode(StrEnum):
    SPECIFIC = "specific"
    CHOOSE = "choose"
    RANDOM = "random"


class LeaderAbilityKind(StrEnum):
    CLEAR_WEATHER = "clear_weather"
    PLAY_WEATHER_FROM_DECK = "play_weather_from_deck"
    HORN_OWN_ROW = "horn_own_row"
    SCORCH_OPPONENT_ROW = "scorch_opponent_row"
    DISCARD_AND_CHOOSE_FROM_DECK = "discard_and_choose_from_deck"
    RETURN_CARD_FROM_OWN_DISCARD_TO_HAND = "return_card_from_own_discard_to_hand"
    DOUBLE_SPY_STRENGTH_GLOBAL = "double_spy_strength_global"
    REVEAL_RANDOM_OPPONENT_HAND_CARDS = "reveal_random_opponent_hand_cards"
    DISABLE_OPPONENT_LEADER = "disable_opponent_leader"
    TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND = "take_card_from_opponent_discard_to_hand"
    RANDOMIZE_RESTORE_TO_BATTLEFIELD_SELECTION = "randomize_restore_to_battlefield_selection"
    DRAW_EXTRA_OPENING_CARD = "draw_extra_opening_card"
    OPTIMIZE_AGILE_ROWS = "optimize_agile_rows"
    SHUFFLE_ALL_DISCARDS_INTO_DECKS = "shuffle_all_discards_into_decks"
    HALVE_WEATHER_PENALTY = "halve_weather_penalty"


BATTLE_ROWS: tuple[Row, ...] = (Row.CLOSE, Row.RANGED, Row.SIEGE)
ACTIVE_TURN_PHASES: tuple[Phase, ...] = (Phase.IN_ROUND,)
WEATHER_ABILITY_KINDS: tuple[AbilityKind, ...] = (
    AbilityKind.BITING_FROST,
    AbilityKind.IMPENETRABLE_FOG,
    AbilityKind.TORRENTIAL_RAIN,
    AbilityKind.SKELLIGE_STORM,
)
