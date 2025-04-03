from typing_extensions import TypedDict
from typing import Any, Optional
from datetime import datetime

from modules import asyncreqs


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
        self.name: str = name
        self.id: str = uuid
        self.last_updated: datetime = last_updated or datetime.now()

    @property
    def uuid(self) -> str:
        return self.id

    @property
    def avatar(self) -> str:
        return f"https://cravatar.eu/helmavatar/{self.id}/600.png"

    def to_dict(self) -> MojangPlayerDict:
        return {
            "id": self.id,
            "name": self.name,
            "lastUpdated": int(self.last_updated.timestamp())
        }

    @classmethod
    def from_dict(cls, data: MojangPlayerDict|RawMojangPlayerDict):
        uuid = data.get('id', data.get('uuid'))
        name = data.get('name', data.get('username'))
        if not isinstance(uuid, str) or not isinstance(name, str):
            raise ValueError("Invalid player data:", data)
        last_updated = datetime.fromtimestamp(data['lastUpdated']) if data.get('lastUpdated') else datetime.now() # type: ignore
        return cls(
            uuid=uuid,
            name=name,
            last_updated=last_updated
        )


async def get(identifier: str) -> MojangPlayer:
    response = await asyncreqs.get("https://api.ragingenby.dev/player/" + identifier)
    if response.status == 404:
        raise PlayerNotFound(identifier)
    data: RawMojangPlayerDict | dict[str, Any] = await response.json()
    try:
        return MojangPlayer.from_dict(data)  # type: ignore
    except ValueError as e:
        raise PlayerNotFound(f"{identifier} - {e}")
