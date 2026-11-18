"""Tracker state and pending alerts in one SQLite database.

Each tracker keeps its state as one JSON document in the state table. A poll
saves its new state and the alerts it found in one transaction, so the bot
never keeps a state change without its alerts or sends alerts for a state it
did not save. The outbox sender in skypixel.storage.notifications delivers
the saved alerts.

Every call opens its own connection in a worker thread through
asyncio.to_thread, so a slow disk never blocks the event loop. A write lock
keeps the bot's own writes in order. Startup work, such as loading state when
a cog is created, runs on the calling thread.
"""

import asyncio
import json
import logging
import sqlite3
import threading
import time
from collections.abc import (
    Callable,
    Generator,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
)
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeGuard, cast

from skypixel.domain.types import JSON
from skypixel.storage.json_store import read_json

if TYPE_CHECKING:
    from disnake.types.embed import Embed as EmbedData

logger: logging.Logger = logging.getLogger(__name__)

SCHEMA_VERSION: int = 1
SCHEMA: str = """
CREATE TABLE state (
    tracker TEXT PRIMARY KEY,
    json TEXT NOT NULL
);
CREATE TABLE outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    thread_id INTEGER,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try REAL NOT NULL,
    created_at REAL NOT NULL,
    sent_at REAL,
    dead INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX outbox_due ON outbox (next_try) WHERE sent_at IS NULL AND dead = 0;
"""

# State files that the bot kept before it used SQLite. Each one becomes the
# state row with the file's name. items.json stays a file.
LEGACY_STATE_FILES: tuple[str, ...] = (
    "alpha",
    "auctions",
    "dmnotices",
    "firesales",
    "jobs",
    "motd",
    "ranks",
    "rankwatchlist",
    "version",
    "zones",
)
LEGACY_TRACKER: str = "migrated"
# Added to an imported file's name, as in ranks.json.migrated.
LEGACY_SUFFIX: str = ".migrated"

# The SQL parameters that the outbox updates pass. int values fit float.
type Parameters = tuple[float, ...]
# One row of _due_alerts(): id, channel_id, thread_id, payload, attempts, and
# created_at.
type OutboxRow = tuple[int, int, int | None, str, int, float]


class AlertPayload(TypedDict):
    """The message that Alert.payload() saves in the outbox payload column."""

    content: str | None
    embeds: list[EmbedData]


def _is_embed_list(value: object) -> TypeGuard[list[EmbedData]]:
    # The JSON outbox saved the output of Embed.to_dict() under "embeds".
    return isinstance(value, list)


@dataclass(frozen=True)
class Alert:
    """One Discord message for the outbox to send."""

    channel_id: int
    content: str | None = None
    embeds: tuple[EmbedData, ...] = ()
    thread_id: int | None = None

    def payload(self) -> str:
        message: AlertPayload = {"content": self.content, "embeds": list(self.embeds)}
        return json.dumps(message)


@dataclass(frozen=True)
class PendingAlert:
    id: int
    alert: Alert
    attempts: int
    created_at: float


class Database:
    def __init__(
        self, path: str | Path, *, legacy_dir: str | Path | None = None
    ) -> None:
        self.path: Path = Path(path)
        self._write_lock: threading.Lock = threading.Lock()
        # Set when a transaction saves alerts, so the sender can wake early.
        self.alerts_saved: asyncio.Event = asyncio.Event()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            if _user_version(connection) == 0:
                self._create(connection, Path(legacy_dir) if legacy_dir else None)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
        with self._write_lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    def _create(self, connection: sqlite3.Connection, legacy_dir: Path | None) -> None:
        """Create the tables and import the JSON files in one transaction."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            if _user_version(connection) != 0:
                connection.execute("ROLLBACK")
                return
            # executescript() would commit the open transaction first.
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            imported: list[str]
            files: list[Path]
            imported, files = (
                _import_legacy(connection, legacy_dir)
                if legacy_dir is not None
                else ([], [])
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")
        logger.info("Created the state database at %s.", self.path)
        for line in imported:
            logger.info(line)
        _retire_legacy(files)

    def load_state(self, tracker: str) -> tuple[bool, dict[str, JSON]]:
        """Return whether the tracker has saved state, and the state."""
        with closing(self._connect()) as connection:
            row: tuple[str] | None = connection.execute(
                "SELECT json FROM state WHERE tracker = ?", (tracker,)
            ).fetchone()
        if row is None:
            return False, {}
        # save() wrote this text from a dict with str keys.
        data: dict[str, JSON] = json.loads(row[0])
        return True, data

    def _save(
        self, tracker: str, data: Mapping[str, object], alerts: Sequence[Alert]
    ) -> None:
        now = time.time()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO state (tracker, json) VALUES (?, ?) "
                "ON CONFLICT (tracker) DO UPDATE SET json = excluded.json",
                (tracker, json.dumps(data)),
            )
            connection.executemany(
                "INSERT INTO outbox (tracker, channel_id, thread_id, payload, "
                "next_try, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        tracker,
                        alert.channel_id,
                        alert.thread_id,
                        alert.payload(),
                        now,
                        now,
                    )
                    for alert in alerts
                ],
            )

    async def save(
        self, tracker: str, data: Mapping[str, object], alerts: Sequence[Alert] = ()
    ) -> None:
        """Save a tracker's state and its new alerts in one transaction."""
        await _run_to_completion(self._save, tracker, data, list(alerts))
        if alerts:
            self.alerts_saved.set()

    def _due_alerts(self, now: float) -> list[PendingAlert]:
        with closing(self._connect()) as connection:
            rows: list[OutboxRow] = connection.execute(
                "SELECT id, channel_id, thread_id, payload, attempts, created_at "
                "FROM outbox WHERE sent_at IS NULL AND dead = 0 AND next_try <= ? "
                "ORDER BY id",
                (now,),
            ).fetchall()
        alerts: list[PendingAlert] = []
        for row_id, channel_id, thread_id, payload, attempts, created_at in rows:
            # Alert.payload() wrote this text.
            message: AlertPayload = json.loads(payload)
            alert = Alert(
                channel_id,
                message["content"],
                tuple(message["embeds"]),
                thread_id,
            )
            alerts.append(PendingAlert(row_id, alert, attempts, created_at))
        return alerts

    async def due_alerts(self, now: float) -> list[PendingAlert]:
        """Return unsent alerts whose next try is at or before now, oldest first."""
        return await asyncio.to_thread(self._due_alerts, now)

    def _update(self, sql: str, parameters: Parameters) -> None:
        with self._transaction() as connection:
            connection.execute(sql, parameters)

    async def mark_sent(self, alert_id: int, now: float) -> None:
        await _run_to_completion(
            self._update, "UPDATE outbox SET sent_at = ? WHERE id = ?", (now, alert_id)
        )

    async def mark_failed(self, alert_id: int, attempts: int, next_try: float) -> None:
        await _run_to_completion(
            self._update,
            "UPDATE outbox SET attempts = ?, next_try = ? WHERE id = ?",
            (attempts, next_try, alert_id),
        )

    async def mark_dead(self, alert_id: int, attempts: int) -> None:
        await _run_to_completion(
            self._update,
            "UPDATE outbox SET attempts = ?, dead = 1 WHERE id = ?",
            (attempts, alert_id),
        )

    async def prune(self, before: float) -> None:
        """Delete finished alerts created before the given time."""
        await _run_to_completion(
            self._update,
            "DELETE FROM outbox WHERE (sent_at IS NOT NULL OR dead = 1) "
            "AND created_at < ?",
            (before,),
        )


def _user_version(connection: sqlite3.Connection) -> int:
    row: tuple[int] = connection.execute("PRAGMA user_version").fetchone()
    return row[0]


async def _run_to_completion[**P, R](
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    """Run a write in a thread and wait for it even if the caller is cancelled.

    A cancelled caller must not release its state lock while the transaction
    may still commit.
    """
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def _retire_legacy(files: list[Path]) -> None:
    """Rename the imported JSON files so they can never be imported again.

    If the database were lost while the files kept their names, the next start
    would import their stale state and send every old pending alert again.
    """
    for path in files:
        try:
            path.rename(path.with_name(path.name + LEGACY_SUFFIX))
        except OSError:
            logger.exception("Cannot rename %s after importing it.", path)


def _import_legacy(
    connection: sqlite3.Connection, directory: Path
) -> tuple[list[str], list[Path]]:
    """Copy the JSON state files into the new tables.

    Return the log lines and the files that were read. The caller renames the
    files after the transaction commits.
    """
    imported: list[str] = []
    files: list[Path] = []
    for name in LEGACY_STATE_FILES:
        path = directory / f"{name}.json"
        if not path.exists():
            continue
        data = read_json(path)
        files.append(path)
        connection.execute(
            "INSERT INTO state (tracker, json) VALUES (?, ?)", (name, json.dumps(data))
        )
        imported.append(f"Imported {path} into the state database ({len(data)} keys).")
    path = directory / "notifications.json"
    if path.exists():
        pending = read_json(path)
        # A message listed as delivered in an event was sent, but the bot
        # stopped before it could remove the message from notifications.json.
        events_path = directory / "notifications.events.json"
        events = read_json(events_path)
        files.append(path)
        if events_path.exists():
            files.append(events_path)
        delivered: set[str] = set()
        for event in events.values():
            if isinstance(event, dict):
                keys = event.get("delivered", [])
                if isinstance(keys, list):
                    delivered.update(key for key in keys if isinstance(key, str))
        rows: list[tuple[str, int, int | None, str, float, float]] = []
        skipped = 0
        for key, message in pending.items():
            if key in delivered or not isinstance(message, dict):
                skipped += 1
                continue
            channel_id = message.get("channel_id")
            content = message.get("content")
            thread_id = message.get("thread_id")
            embeds = message.get("embeds") or []
            # A message saved before messages recorded their age starts its
            # clock now, so it still gets the full retry window.
            created_at = message.get("created_at", time.time())
            if (
                not isinstance(channel_id, int)
                or not isinstance(content, str | None)
                or not isinstance(thread_id, int | None)
                or not isinstance(created_at, int | float)
                or not _is_embed_list(embeds)
            ):
                skipped += 1
                continue
            alert = Alert(channel_id, content, tuple(embeds), thread_id)
            rows.append(
                (
                    LEGACY_TRACKER,
                    alert.channel_id,
                    alert.thread_id,
                    alert.payload(),
                    0.0,
                    float(created_at),
                )
            )
        connection.executemany(
            "INSERT INTO outbox (tracker, channel_id, thread_id, payload, "
            "next_try, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        imported.append(
            f"Imported {len(rows)} pending alerts from {path} "
            f"and skipped {skipped} that were delivered or malformed."
        )
    if not imported:
        imported.append(f"Found no JSON state files to import in {directory}.")
    return imported, files


class TrackerState[V = JSON](MutableMapping[str, V]):
    """One tracker's state, kept in memory and saved to the database.

    The in-memory copy changes only after a save commits, so a failed save
    leaves the tracker on its old state and the next poll tries again.

    V is the type of each value. It defaults to any JSON value. A tracker that
    stores one shape, such as a TypedDict, can name it as V.
    """

    def __init__(self, database: Database, tracker: str) -> None:
        self.database: Database = database
        self.tracker: str = tracker
        exists, data = database.load_state(tracker)
        self.exists: bool = exists
        # The row holds what this tracker saved, so its values have type V.
        # The checker cannot see that through json.loads.
        self.data: dict[str, V] = cast("dict[str, V]", data)
        self._save_lock: asyncio.Lock = asyncio.Lock()

    def __getitem__(self, key: str) -> V:
        return self.data[key]

    def __setitem__(self, key: str, value: V) -> None:
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        del self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def to_dict(self) -> dict[str, V]:
        return self.data

    async def replace(self, data: dict[str, V], alerts: Sequence[Alert] = ()) -> None:
        """Save new state and the alerts it caused in one transaction."""
        async with self._save_lock:
            await self._replace(data, alerts)

    async def set_and_save(self, key: str, value: V) -> None:
        async with self._save_lock:
            await self._replace({**self.data, key: value})

    async def remove_and_save(self, key: str) -> None:
        async with self._save_lock:
            await self._replace(
                {name: value for name, value in self.data.items() if name != key}
            )

    async def _replace(self, data: dict[str, V], alerts: Sequence[Alert] = ()) -> None:
        await self.database.save(self.tracker, data, alerts)
        self.data = data
        self.exists = True
        logger.debug("Saved %s state.", self.tracker)
