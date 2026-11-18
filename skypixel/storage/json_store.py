import asyncio
import json
import logging
import os
import stat
import tempfile
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
