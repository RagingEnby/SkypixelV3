import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import ClassVar, TypedDict

from skypixel import constants
from skypixel.clients import http as asyncreqs

logger = logging.getLogger(__name__)
PLAYER_URL = "https://api.ragingenby.dev/player/{}"
PLAYERS_URL = "https://api.ragingenby.dev/players"


def normalize_identifier(identifier: str) -> str:
    return identifier.replace("-", "").lower()


class Cache:
    TTL = timedelta(minutes=30)
    CACHE: ClassVar[dict[str, "MojangPlayer"]] = {}

    @staticmethod
    def cleanup() -> None:
        now = datetime.now(UTC)
        for key, player in list(Cache.CACHE.items()):
            if now - player.last_updated >= Cache.TTL:
                del Cache.CACHE[key]

    @staticmethod
    def cache_player(player: "MojangPlayer") -> None:
        Cache.CACHE[normalize_identifier(player.id)] = player
        Cache.CACHE[player.name.lower()] = player

    @staticmethod
    def get(key: str) -> "MojangPlayer | None":
        Cache.cleanup()
        return Cache.CACHE.get(normalize_identifier(key))


class PlayerNotFound(KeyError):
    pass


class RawMojangPlayerDict(TypedDict):
    id: str
    name: str


class MojangPlayerDict(RawMojangPlayerDict):
    lastUpdated: int


class MojangPlayer:
    def __init__(self, name: str, uuid: str, last_updated: datetime | None = None):
        self.name = name
        self.id = uuid
        self.last_updated = (last_updated or datetime.now(UTC)).astimezone(UTC)
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
            "lastUpdated": int(self.last_updated.timestamp()),
        }

    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict):
            raise ValueError("Expected a player object.")
        uuid = data.get("id", data.get("uuid"))
        name = data.get("name", data.get("username"))
        if (
            not isinstance(uuid, str)
            or not isinstance(name, str)
            or not uuid
            or not name
        ):
            raise ValueError("The player object needs an id and a name.")
        updated = data.get("lastUpdated")
        last_updated = (
            datetime.fromtimestamp(updated, UTC) if updated else datetime.now(UTC)
        )
        return cls(uuid=uuid, name=name, last_updated=last_updated)


_inflight: dict[str, asyncio.Task[MojangPlayer]] = {}


def _finish_fetch(key: str, task: asyncio.Task[MojangPlayer]) -> None:
    if _inflight.get(key) is task:
        _inflight.pop(key)
    if not task.cancelled():
        task.exception()


async def close() -> None:
    tasks = list(_inflight.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _inflight.clear()


async def _fetch(identifier: str) -> MojangPlayer:
    response = await asyncreqs.get(PLAYER_URL.format(identifier))
    if response.status_code == 404:
        raise PlayerNotFound(identifier)
    response.raise_for_status()
    try:
        return MojangPlayer.from_dict(response.json())
    except (ValueError, TypeError, OverflowError) as error:
        raise PlayerNotFound(identifier) from error


async def get(identifier: str) -> MojangPlayer:
    if cached := Cache.get(identifier):
        return cached
    key = normalize_identifier(identifier)
    if key not in _inflight:
        task = asyncio.create_task(_fetch(identifier), name=f"player-{key}")
        _inflight[key] = task
        task.add_done_callback(lambda finished: _finish_fetch(key, finished))
    return await asyncio.shield(_inflight[key])


async def bulk(identifiers: list[str]) -> dict[str, MojangPlayer]:
    players = {}
    missing = []
    for identifier in dict.fromkeys(identifiers):
        key = normalize_identifier(identifier)
        if cached := Cache.get(key):
            players[key] = cached
        else:
            missing.append(key)
    if missing:
        response = await asyncreqs.post(
            PLAYERS_URL, json={"identifiers": list(dict.fromkeys(missing))}
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("players"), list):
            raise ValueError("The player API did not return a players list.")
        for raw in data["players"]:
            player = MojangPlayer.from_dict(raw)
            for key in (normalize_identifier(player.id), player.name.lower()):
                if key in missing:
                    players[key] = player
    return {
        identifier
        if normalize_identifier(identifier) == player.id.lower()
        else identifier.lower(): player
        for identifier in identifiers
        if (player := players.get(normalize_identifier(identifier))) is not None
    }
