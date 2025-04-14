import logging
from datetime import datetime
from typing import Any, Optional

from typing_extensions import TypedDict

import constants
from modules import asyncreqs

logger = logging.getLogger(__name__)


class PlayerNotFound(KeyError):
    pass


class RawMojangPlayerDict(TypedDict):
    id: str
    name: str


class MojangPlayerDict(RawMojangPlayerDict):
    id: str
    name: str
    lastUpdated: int


class MojangPlayer:
    def __init__(self, name: str, uuid: str, last_updated: Optional[datetime] = None):
        logger.debug(f"initializing MojangPlayer({name}, {uuid}, {last_updated})")
        self.name: str = name
        self.id: str = uuid
        self.last_updated: datetime = last_updated or datetime.now()

    @property
    def uuid(self) -> str:
        return self.id

    @property
    def avatar(self) -> str:
        return constants.MC_HEAD_IMAGE.format(self.id)

    def to_dict(self) -> MojangPlayerDict:
        return {
            "id": self.id,
            "name": self.name,
            "lastUpdated": int(self.last_updated.timestamp())
        }

    @classmethod
    def from_dict(cls, data: MojangPlayerDict|RawMojangPlayerDict):
        logger.debug(f"creating MojangPlayer from {data}")
        uuid = data.get('id', data.get('uuid'))
        name = data.get('name', data.get('username'))
        logger.debug(f"uuid: {uuid}, name: {name}")
        if not isinstance(uuid, str) or not isinstance(name, str):
            raise ValueError("Invalid player data:", data)
        last_updated = datetime.fromtimestamp(data['lastUpdated']) if data.get('lastUpdated') else datetime.now() # type: ignore
        return cls(
            uuid=uuid,
            name=name,
            last_updated=last_updated
        )


async def get(identifier: str) -> MojangPlayer:
    logger.debug(f"getting player {identifier}...")
    response = await asyncreqs.get("https://api.ragingenby.dev/player/" + identifier)
    logger.debug("got response:", response.status)
    if response.status == 404:
        logger.error("invalid identifier:", identifier)
        raise PlayerNotFound(identifier)
    data: RawMojangPlayerDict | dict[str, Any] = await response.json()
    logger.debug("got data:", data)
    try:
        return MojangPlayer.from_dict(data)  # type: ignore
    except ValueError as e:
        raise PlayerNotFound(f"{identifier} - {e}")


async def bulk(identifiers: list[str]) -> dict[str, MojangPlayer]:
    logger.debug(f"getting players {identifiers}...")
    response = await asyncreqs.post(
        url="https://api.ragingenby.dev/players",
        json={"identifiers": [i.replace('-', '') for i in identifiers]}
    )
    logger.debug("got response:", response.status)
    data = await response.json()
    logger.debug("got data:", data)
    players = [MojangPlayer.from_dict(player) for player in data['players']]
    logger.debug("got players:", players)
    return {
        (player.id if player.id in identifiers else player.name.lower()): player
        for player in players
    }
