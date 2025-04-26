import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from typing_extensions import TypedDict

import constants
from modules import asyncreqs

logger = logging.getLogger(__name__)


class Cache:
    TTL = timedelta(minutes=30)
    CACHE: dict[str, "MojangPlayer"] = {}

    @staticmethod
    def cleanup():
        now = datetime.now()
        expired = [
            key
            for key, player in Cache.CACHE.items()
            if now - player.last_updated >= Cache.TTL
        ]
        for key in expired:
            del Cache.CACHE[key]

    @staticmethod
    def cache_player(player: "MojangPlayer"):
        Cache.CACHE[player.id] = player
        Cache.CACHE[player.name.lower()] = player

    @staticmethod
    def get(key: str) -> Optional["MojangPlayer"]:  # type: ignore[assignment]
        Cache.cleanup()
        player = Cache.CACHE.get(key)
        if not player:
            return None
        if datetime.now() - player.last_updated < Cache.TTL:
            logger.debug(f"cache hit for {key}: {player}")
            return player
        logger.debug(f"cache expired for {key}")
        del Cache.CACHE[key]
        return None


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
    def __init__(self, name: str, uuid: str, last_updated: datetime | None = None):
        logger.debug(f"initializing MojangPlayer({name}, {uuid}, {last_updated})")
        self.name: str = name
        self.id: str = uuid
        self.last_updated: datetime = last_updated or datetime.now()
        Cache.cache_player(self)

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
    cached = Cache.get(identifier)
    if cached:
        return cached
    response = await asyncreqs.get("https://api.ragingenby.dev/player/" + identifier)
    if response.status == 404:
        logger.error("invalid identifier:", identifier)
        raise PlayerNotFound(identifier)
    data: RawMojangPlayerDict | dict[str, Any] = await response.json()
    logger.debug(f"got data: {data}")
    try:
        return MojangPlayer.from_dict(data)  # type: ignore
    except ValueError as e:
        raise PlayerNotFound(f"{identifier} - {e}")


async def bulk(identifiers: list[str]) -> dict[str, MojangPlayer]:
    logger.debug(f"getting players {identifiers}...")
    to_fetch = identifiers.copy()
    players: list[MojangPlayer] = []
    for identifier in identifiers:
        cached = Cache.get(identifier)
        if cached:
            players.append(cached)
            to_fetch.remove(identifier)
    if to_fetch:
        response = await asyncreqs.post(
            url="https://api.ragingenby.dev/players",
            json={"identifiers": [i.replace('-', '') for i in identifiers]}
        )
        data = await response.json()
        logger.debug(f"got data: {data}")
        for player in data['players']:
            players.append(MojangPlayer.from_dict(player))
    return {
        (player.id if player.id in identifiers else player.name.lower()): player
        for player in players
    }
