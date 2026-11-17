import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from typing import ClassVar, TypedDict

from skypixel import constants
from skypixel.clients import http

PLAYER_URL = "https://api.ragingenby.dev/player/{}"
PLAYERS_URL = "https://api.ragingenby.dev/players"
NAME_PATTERN = re.compile(r"[A-Za-z0-9_]{1,16}")
UUID_PATTERN = re.compile(r"[0-9a-f]{32}")


def normalize_identifier(identifier: str) -> str:
    return identifier.replace("-", "").lower()


def is_valid_identifier(identifier: str) -> bool:
    """Accept a Minecraft username or a UUID with or without dashes."""
    return bool(
        NAME_PATTERN.fullmatch(identifier)
        or UUID_PATTERN.fullmatch(normalize_identifier(identifier))
    )


class Cache:
    TTL = timedelta(minutes=30)
    MAX_ENTRIES = 2048
    CACHE: ClassVar[dict[str, MojangPlayer]] = {}

    @staticmethod
    def expired(player: MojangPlayer) -> bool:
        # last_updated comes from the API and can be older than the TTL, so the
        # cache measures age from when this process stored the player.
        return time.monotonic() - player.cached_at >= Cache.TTL.total_seconds()

    @staticmethod
    def cleanup() -> None:
        for key, player in list(Cache.CACHE.items()):
            if Cache.expired(player):
                del Cache.CACHE[key]

    @staticmethod
    def cache_player(player: MojangPlayer) -> None:
        Cache.cleanup()
        uuid = normalize_identifier(player.id)
        previous = Cache.CACHE.get(uuid)
        if previous is not None and Cache.CACHE.get(previous.name.lower()) is previous:
            Cache.CACHE.pop(previous.name.lower())
        Cache.CACHE.pop(uuid, None)
        Cache.CACHE[uuid] = player
        Cache.CACHE[player.name.lower()] = player
        while len(Cache.CACHE) > Cache.MAX_ENTRIES:
            Cache.CACHE.pop(next(iter(Cache.CACHE)))

    @staticmethod
    def get(key: str) -> MojangPlayer | None:
        key = normalize_identifier(key)
        player = Cache.CACHE.get(key)
        if player is not None and Cache.expired(player):
            Cache.CACHE.pop(key)
            return None
        return player


class PlayerNotFound(KeyError):
    pass


class PlayerLookupError(RuntimeError):
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
        self.cached_at = time.monotonic()
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
    response = await http.get(PLAYER_URL.format(identifier))
    if response.status_code == 404:
        raise PlayerNotFound(identifier)
    response.raise_for_status()
    try:
        return MojangPlayer.from_dict(response.json())
    except (ValueError, TypeError, OverflowError, OSError) as error:
        # The API answered, but not with a player. That is an API fault, so do
        # not tell the user that the player does not exist.
        raise PlayerLookupError(
            f"The player API returned an unreadable answer for {identifier}."
        ) from error


async def get(identifier: str) -> MojangPlayer:
    if not is_valid_identifier(identifier):
        raise PlayerNotFound(identifier)
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
    missing = {}
    for key in dict.fromkeys(map(normalize_identifier, identifiers)):
        if cached := Cache.get(key):
            players[key] = cached
        else:
            missing[key] = None
    if missing:
        response = await http.post(PLAYERS_URL, json={"identifiers": list(missing)})
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
        if normalize_identifier(identifier) == normalize_identifier(player.id)
        else identifier.lower(): player
        for identifier in identifiers
        if (player := players.get(normalize_identifier(identifier))) is not None
    }
