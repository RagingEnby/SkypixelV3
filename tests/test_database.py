import asyncio
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from skypixel.domain.types import JSONInput
from skypixel.storage import database as database_module
from skypixel.storage.database import Alert, Database, TrackerState
from skypixel.storage.json_store import StorageError


class TrackerStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path: Path = Path(self.directory.name) / "skypixel.db"
        self.database: Database = Database(self.path)

    async def test_save_and_reload(self) -> None:
        state = TrackerState(self.database, "ranks")
        self.assertFalse(state.exists)
        await state.replace({"player": {"rank": "staff", "name": "Player"}})
        reloaded = TrackerState(Database(self.path), "ranks")
        self.assertTrue(reloaded.exists)
        self.assertEqual(reloaded.to_dict(), state.to_dict())
        self.assertEqual(TrackerState(self.database, "zones").to_dict(), {})

    async def test_database_uses_wal_mode(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            row: tuple[str] = connection.execute("PRAGMA journal_mode").fetchone()
        mode = row[0]
        self.assertEqual(mode, "wal")

    async def test_replace_updates_memory_only_after_a_successful_save(self) -> None:
        state = TrackerState(self.database, "motd")
        await state.replace({"old": 1})
        with patch.object(self.database, "_save", side_effect=OSError):
            with self.assertRaises(OSError):
                await state.replace({"new": 2})
        self.assertEqual(state.to_dict(), {"old": 1})
        self.assertEqual(TrackerState(self.database, "motd").to_dict(), {"old": 1})
        await state.replace({"new": 2})
        self.assertEqual(TrackerState(self.database, "motd").to_dict(), {"new": 2})

    async def test_failed_save_rolls_back_the_state_and_its_alerts(self) -> None:
        state = TrackerState(self.database, "version")
        alert = Alert(1, "ping")
        with patch.object(Alert, "payload", side_effect=ValueError("bad alert")):
            with self.assertRaises(ValueError):
                await state.replace({"version": "new"}, [alert])
        self.assertFalse(TrackerState(self.database, "version").exists)
        self.assertEqual(await self.database.due_alerts(float("inf")), [])

    async def test_concurrent_watchlist_edits_preserve_both_updates(self) -> None:
        state = TrackerState(self.database, "rankwatchlist")
        started, release = asyncio.Event(), asyncio.Event()
        original = self.database.save

        async def save(
            tracker: str, data: Mapping[str, object], alerts: Sequence[Alert] = ()
        ) -> None:
            if data == {"first": 1}:
                started.set()
                await release.wait()
            await original(tracker, data, alerts)

        with patch.object(self.database, "save", side_effect=save):
            first = asyncio.create_task(state.set_and_save("first", 1))
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(state.set_and_save("second", 2))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)
            await state.remove_and_save("first")
        self.assertEqual(state.to_dict(), {"second": 2})
        self.assertEqual(
            TrackerState(self.database, "rankwatchlist").to_dict(), {"second": 2}
        )

    async def test_mapping_views_follow_loaded_and_replaced_data(self) -> None:
        await TrackerState(self.database, "alpha").replace({"old": 1})
        state = TrackerState(self.database, "alpha")
        self.assertEqual(list(state.items()), [("old", 1)])
        state.data = {"new": 2}
        self.assertEqual(list(state.keys()), ["new"])
        self.assertEqual(list(state.values()), [2])

    async def test_cancelled_save_commits_before_releasing_the_lock(self) -> None:
        state = TrackerState(self.database, "jobs")
        started = asyncio.Event()
        release, second_started = threading.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        original = self.database._save  # pyright: ignore[reportPrivateUsage]

        def save(
            tracker: str, data: Mapping[str, object], alerts: Sequence[Alert]
        ) -> None:
            if data == {"first": 1}:
                loop.call_soon_threadsafe(started.set)
                if not release.wait(timeout=2):
                    raise TimeoutError("The test did not release the first save.")
            else:
                second_started.set()
            original(tracker, data, alerts)

        with patch.object(self.database, "_save", side_effect=save):
            first = asyncio.create_task(state.replace({"first": 1}))
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                first.cancel()
                second = asyncio.create_task(state.replace({"second": 2}))
                await asyncio.sleep(0)
                self.assertFalse(first.done())
                self.assertFalse(second_started.is_set())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await first
            await second
        self.assertEqual(TrackerState(self.database, "jobs").to_dict(), {"second": 2})

    async def test_saves_run_off_the_event_loop(self) -> None:
        threads: list[int] = []
        original = self.database._save  # pyright: ignore[reportPrivateUsage]

        def save(
            tracker: str, data: Mapping[str, object], alerts: Sequence[Alert]
        ) -> None:
            threads.append(threading.get_ident())
            original(tracker, data, alerts)

        with patch.object(self.database, "_save", side_effect=save):
            await TrackerState(self.database, "zones").replace({"zones": []})
        self.assertNotEqual(threads, [threading.get_ident()])


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage: Path = Path(self.directory.name)
        self.path: Path = self.storage / "skypixel.db"

    def write(self, name: str, data: JSONInput) -> None:
        (self.storage / name).write_text(json.dumps(data))

    def open(self) -> Database:
        return Database(self.path, legacy_dir=self.storage)

    def test_first_start_imports_every_state_file_and_keeps_the_files(self) -> None:
        files = {
            name: {"key": name}
            for name in (
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
        }
        for name, data in files.items():
            self.write(f"{name}.json", data)
        self.write("items.json", {"items": []})
        before = {path.name: path.read_bytes() for path in self.storage.iterdir()}
        with self.assertLogs(database_module.logger, level="INFO") as logs:
            database = self.open()
        for name, data in files.items():
            self.assertEqual(TrackerState(database, name).to_dict(), data)
        self.assertFalse(TrackerState(database, "items").exists)
        after = {
            path.name: path.read_bytes()
            for path in self.storage.iterdir()
            if not path.name.startswith("skypixel.db")
        }
        # Each imported file keeps its contents under a new name. items.json
        # is not state, so it keeps its name.
        expected = {
            name if name == "items.json" else name + ".migrated": content
            for name, content in before.items()
        }
        self.assertEqual(after, expected)
        self.assertEqual(sum("Imported" in line for line in logs.output), len(files))

    def test_missing_and_empty_files_keep_first_run_detection(self) -> None:
        self.write("jobs.json", {})
        database = self.open()
        jobs = TrackerState(database, "jobs")
        self.assertTrue(jobs.exists)
        self.assertEqual(jobs.to_dict(), {})
        self.assertFalse(TrackerState(database, "firesales").exists)

    def test_pending_alerts_are_imported_and_delivered_ones_are_skipped(self) -> None:
        self.write(
            "notifications.json",
            {
                "event:sent": {"channel_id": 1, "content": "a", "embeds": []},
                "event:pending": {
                    "channel_id": 2,
                    "thread_id": 3,
                    "content": "ping",
                    "embeds": [{"title": "Alert"}],
                    "event_id": "event",
                    "created_at": 1234.5,
                },
                "event:no-age": {"channel_id": 6, "content": "old", "embeds": []},
                "broken": {"content": "no channel"},
                "bad-time": {"channel_id": 4, "created_at": "yesterday"},
                "bad-embeds": {"channel_id": 5, "embeds": {"title": "Alert"}},
            },
        )
        self.write(
            "notifications.events.json",
            {"event": {"complete": False, "delivered": ["event:sent"]}},
        )
        with self.assertLogs(database_module.logger, level="INFO") as logs:
            database = self.open()
        pending = asyncio.run(database.due_alerts(0))
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0].alert, Alert(2, "ping", ({"title": "Alert"},), 3))
        self.assertEqual(pending[0].created_at, 1234.5)
        # A message saved before messages recorded their age gets a full window.
        self.assertEqual(pending[1].alert.channel_id, 6)
        self.assertGreater(pending[1].created_at, time.time() - 60)
        self.assertIn("Imported 2 pending alerts", "\n".join(logs.output))
        self.assertFalse((self.storage / "notifications.json").exists())
        for name in ("notifications.json", "notifications.events.json"):
            self.assertTrue((self.storage / (name + ".migrated")).exists())

    def test_a_lost_database_does_not_import_the_old_files_again(self) -> None:
        self.write("version.json", {"version": "one"})
        self.write("notifications.json", {"a": {"channel_id": 1, "embeds": []}})
        self.open()
        for path in self.storage.glob("skypixel.db*"):
            path.unlink()
        database = self.open()
        self.assertFalse(TrackerState(database, "version").exists)
        self.assertEqual(asyncio.run(database.due_alerts(float("inf"))), [])

    def test_import_runs_only_once(self) -> None:
        self.write("version.json", {"version": "one"})
        self.open()
        self.write("version.json", {"version": "two"})
        self.write("notifications.json", {"a": {"channel_id": 1, "embeds": []}})
        database = self.open()
        self.assertEqual(TrackerState(database, "version")["version"], "one")
        self.assertEqual(asyncio.run(database.due_alerts(float("inf"))), [])

    def test_corrupt_file_stops_the_import_and_a_later_start_retries_it(self) -> None:
        self.write("version.json", {"version": "one"})
        (self.storage / "ranks.json").write_text('{"unfinished":')
        with self.assertRaises(StorageError):
            self.open()
        with closing(sqlite3.connect(self.path)) as connection:
            version: tuple[int] = connection.execute("PRAGMA user_version").fetchone()
            tables: list[tuple[str]] = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        self.assertEqual(version[0], 0)
        self.assertEqual(tables, [])
        self.write("ranks.json", {"a": {"name": "A", "rank": "staff"}})
        database = self.open()
        self.assertEqual(TrackerState(database, "version")["version"], "one")
        self.assertIn("a", TrackerState(database, "ranks"))

    def test_trackers_read_the_imported_state(self) -> None:
        from skypixel.trackers import firesaletracker, ranktracker
        from tests import support

        self.write("firesales.json", {})
        self.write("ranks.json", {})
        bot = support.make_bot(database=self.open())
        self.assertTrue(firesaletracker.FireSaleTrackerCog(bot).initialized)
        with self.assertLogs(ranktracker.logger, level="WARNING"):
            ranks = ranktracker.RankTrackerCog(bot)
        self.assertEqual(ranks.data.to_dict(), {})
