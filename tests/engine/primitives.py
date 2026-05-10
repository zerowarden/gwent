from gwent_engine.core import Row, Zone
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId, PlayerId
from gwent_engine.core.state import CardInstance

PLAYER_ONE_ID = PlayerId("p1")
PLAYER_TWO_ID = PlayerId("p2")


def make_card_instance(
    *,
    instance_id: str,
    definition_id: str,
    owner: PlayerId,
    zone: Zone,
    row: Row | None = None,
    battlefield_side: PlayerId | None = None,
) -> CardInstance:
    return CardInstance(
        instance_id=CardInstanceId(instance_id),
        definition_id=CardDefinitionId(definition_id),
        owner=owner,
        zone=zone,
        row=row,
        battlefield_side=battlefield_side,
    )


def battlefield_card(
    *,
    instance_id: str,
    definition_id: str,
    owner: PlayerId,
    row: Row,
    battlefield_side: PlayerId | None = None,
) -> CardInstance:
    return make_card_instance(
        instance_id=instance_id,
        definition_id=definition_id,
        owner=owner,
        zone=Zone.BATTLEFIELD,
        row=row,
        battlefield_side=battlefield_side or owner,
    )


def weather_card(
    *,
    instance_id: str,
    definition_id: str,
    owner: PlayerId,
    row: Row,
) -> CardInstance:
    return make_card_instance(
        instance_id=instance_id,
        definition_id=definition_id,
        owner=owner,
        zone=Zone.WEATHER,
        row=row,
    )
