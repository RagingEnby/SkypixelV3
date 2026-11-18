import asyncio
import json
import logging
import os
import stat
import tempfile
from collections.abc import Iterator, MutableMapping
from contextlib import suppress
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StorageError(ValueError):
    pass


def read_json(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path)
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StorageError(
            f"Cannot read JSON from {path}. Repair the file before starting the bot."
        ) from error
    if not isinstance(data, dict):
        raise StorageError(f"Expected a JSON object in {path}.")
    return data


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        # Temporary files are created with mode 0600. Keep the old file's mode.
        with suppress(FileNotFoundError):
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def write_json(file_path: str | Path, data: dict, indent: int = 2) -> None:
    content = json.dumps(data, indent=indent)
    task = asyncio.create_task(
        asyncio.to_thread(_write_atomic, Path(file_path), content)
    )
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class JsonWrapper(MutableMapping[str, Any]):
    """Keep tracker state in a JSON object and replace the file on save."""

    def __init__(self, file_path: str | Path):
        self.file_path = str(file_path)
        self.data = read_json(file_path)
        self._save_lock = asyncio.Lock()

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        del self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def to_dict(self) -> dict[str, Any]:
        return self.data

    async def save(self, indent: int = 2) -> None:
        await self.replace(self.data, indent)

    async def replace(self, data: dict[str, Any], indent: int = 2) -> None:
        async with self._save_lock:
            await self._replace(data, indent)

    async def set_and_save(self, key: str, value: Any) -> None:
        async with self._save_lock:
            await self._replace({**self.data, key: value})

    async def remove_and_save(self, key: str) -> None:
        async with self._save_lock:
            await self._replace(
                {name: value for name, value in self.data.items() if name != key}
            )

    async def _replace(self, data: dict[str, Any], indent: int = 2) -> None:
        await write_json(self.file_path, data, indent)
        self.data = data
        logger.debug("Saved tracker state to %s", self.file_path)
