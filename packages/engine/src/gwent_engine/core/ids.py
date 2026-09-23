from typing import NewType

CardDefinitionId = NewType("CardDefinitionId", str)
CardInstanceId = NewType("CardInstanceId", str)
ChoiceId = NewType("ChoiceId", str)
DeckId = NewType("DeckId", str)
GameId = NewType("GameId", str)
LeaderId = NewType("LeaderId", str)
PlayerId = NewType("PlayerId", str)


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
    "player_id",
]
