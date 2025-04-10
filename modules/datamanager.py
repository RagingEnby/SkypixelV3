from typing import Any, ItemsView
from contextlib import suppress
import json
import os

from modules import utils


class JsonWrapper:
    def __init__(self, file_path: str):
        self.file_path = file_path
        
        dir = os.path.dirname(file_path)
        if not os.path.exists(dir):
            os.makedirs(dir)
            
        self.data: dict[str, Any] = {}
        with suppress(FileNotFoundError), open(self.file_path) as file:
            self.data: dict[str, Any] = json.load(file)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any):
        self.data[key] = value

    def __delitem__(self, key: str):
        del self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def items(self) -> ItemsView[str, Any]:
        return self.data.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def update(self, data: dict[str, Any]):
        return self.data.update(data)

    def to_dict(self) -> dict[str, Any]:
        return self.data

    async def save(self, indent: int = 2):
        await utils.write_json(self.file_path, self.data, indent)
