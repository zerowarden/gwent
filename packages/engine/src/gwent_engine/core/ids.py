from typing import NewType

CardDefinitionId = NewType("CardDefinitionId", str)
CardInstanceId = NewType("CardInstanceId", str)
ChoiceId = NewType("ChoiceId", str)
DeckId = NewType("DeckId", str)
GameId = NewType("GameId", str)
LeaderId = NewType("LeaderId", str)
PlayerId = NewType("PlayerId", str)


def card_definition_id(value: str) -> CardDefinitionId:
    return CardDefinitionId(value)


def card_instance_id(value: str) -> CardInstanceId:
    return CardInstanceId(value)


def choice_id(value: str) -> ChoiceId:
    return ChoiceId(value)


def deck_id(value: str) -> DeckId:
    return DeckId(value)


def game_id(value: str) -> GameId:
    return GameId(value)


def leader_id(value: str) -> LeaderId:
    return LeaderId(value)


def player_id(value: str) -> PlayerId:
    return PlayerId(value)


__all__ = [
    "CardDefinitionId",
    "CardInstanceId",
    "ChoiceId",
    "DeckId",
    "GameId",
    "LeaderId",
    "PlayerId",
    "card_definition_id",
    "card_instance_id",
    "choice_id",
    "deck_id",
    "game_id",
    "leader_id",
    "player_id",
]
