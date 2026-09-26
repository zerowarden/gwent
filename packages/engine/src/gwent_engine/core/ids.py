from typing import NewType

CardDefinitionId = NewType("CardDefinitionId", str)
CardInstanceId = NewType("CardInstanceId", str)
ChoiceId = NewType("ChoiceId", str)
DeckId = NewType("DeckId", str)
GameId = NewType("GameId", str)
LeaderId = NewType("LeaderId", str)
PlayerId = NewType("PlayerId", str)

PLAYER_ONE = PlayerId("p1")
PLAYER_TWO = PlayerId("p2")


def player_id(value: str) -> PlayerId:
    return PlayerId(value)


def card_definition_id(value: str) -> CardDefinitionId:
    return CardDefinitionId(value)


def card_instance_id(value: str) -> CardInstanceId:
    return CardInstanceId(value)


def choice_id(value: str) -> ChoiceId:
    return ChoiceId(value)


def leader_id(value: str) -> LeaderId:
    return LeaderId(value)


__all__ = [
    "PLAYER_ONE",
    "PLAYER_TWO",
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
    "leader_id",
    "player_id",
]
