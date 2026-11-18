import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import disnake

from skypixel import utils
from skypixel.storage import notifications
from skypixel.storage.database import Database
from skypixel.storage.notifications import Outbox
from skypixel.trackers import auctionhouse, versiontracker


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "skypixel.db"
        self.channel = Mock(spec=disnake.TextChannel)
        self.channel.send = AsyncMock(return_value=Mock(spec=disnake.Message))
        self.bot = SimpleNamespace(
            get_channel=Mock(return_value=self.channel),
            settings=SimpleNamespace(
                storage_dir=Path(self.directory.name), mongodb_uri="mongodb://localhost"
            ),
        )
        self.restart()

    def restart(self):
        """Open the database again, as the bot does when it starts."""
        self.bot.database = Database(self.path)
        self.bot.notifications = Outbox(self.bot, self.bot.database)

    def rows(self) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT channel_id, thread_id, attempts, sent_at IS NOT NULL, dead "
                "FROM outbox ORDER BY id"
            ).fetchall()

    def unsent(self) -> int:
        return sum(1 for row in self.rows() if not row[3] and not row[4])

    def failure(self):
        return disnake.HTTPException(Mock(status=503, reason="Unavailable"), "failure")

    def version_cog(self, version="old"):
        cog = versiontracker.VersionTrackerCog(self.bot)
        cog.data.data = {"version": version}
        return cog

    async def test_alert_saved_with_state_survives_a_restart_and_is_sent(self):
        cog = self.version_cog()
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                versiontracker.constants, "VERSION_TRACKER_CHANNELS", {1: "ping"}
            ),
        ):
            await cog.poll()
        self.channel.send.assert_not_awaited()
        self.restart()
        self.assertEqual(
            versiontracker.VersionTrackerCog(self.bot).data["version"], "new"
        )
        await self.bot.notifications.flush()
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.args, ("ping",))
        self.assertEqual(
            self.channel.send.call_args.kwargs["embeds"][0].description,
            "`old` ➡ `new`",
        )
        self.assertEqual(self.unsent(), 0)

    async def test_state_save_failure_does_not_send_alerts(self):
        cog = self.version_cog()
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                versiontracker.constants, "VERSION_TRACKER_CHANNELS", {1: "ping"}
            ),
            patch.object(self.bot.database, "_save", side_effect=OSError("disk")),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
        self.assertEqual(cog.data["version"], "old")
        await self.bot.notifications.flush()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.rows(), [])

    async def test_each_saved_change_sends_its_own_alert(self):
        cog = self.version_cog()
        with (
            patch.object(
                versiontracker, "get_version", side_effect=["new", "new", "old", "new"]
            ),
            patch.object(
                versiontracker.constants, "VERSION_TRACKER_CHANNELS", {1: "ping"}
            ),
        ):
            for _ in range(4):
                await cog.poll()
                await self.bot.notifications.flush()
        self.assertEqual(self.channel.send.await_count, 3)
        self.assertEqual(cog.data["version"], "new")

    async def test_failed_alert_retries_with_its_thread_after_a_restart(self):
        self.bot.get_channel.return_value = None
        await self.bot.database.save(
            "test",
            {},
            [
                utils.make_alert(
                    1, "ping", thread_id=2, embed=disnake.Embed(title="Alert")
                )
            ],
        )
        with self.assertLogs(utils.logger, level="WARNING"):
            await self.bot.notifications.flush()
        self.assertEqual(self.rows(), [(1, 2, 1, 0, 0)])
        self.restart()
        self.channel.get_thread.return_value = self.channel
        self.bot.get_channel.return_value = self.channel
        await self.bot.notifications.flush(due_only=False)
        self.channel.get_thread.assert_called_with(2)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.args, ("ping",))
        self.assertEqual(self.channel.send.call_args.kwargs["embeds"][0].title, "Alert")
        self.assertEqual(self.unsent(), 0)

    async def test_broadcast_retries_only_the_failed_destination(self):
        good = self.channel
        bad = Mock(spec=disnake.TextChannel)
        bad.send = AsyncMock(side_effect=[self.failure(), Mock(spec=disnake.Message)])
        self.bot.get_channel.side_effect = lambda channel_id: (
            good if channel_id == 1 else bad
        )
        alerts = utils.broadcast({1: "first", 2: "second"}, embed=disnake.Embed())
        await self.bot.database.save("test", {}, alerts)
        with self.assertLogs(utils.logger, level="ERROR"):
            await self.bot.notifications.flush()
        self.assertEqual(self.unsent(), 1)
        await self.bot.notifications.flush(due_only=False)
        good.send.assert_awaited_once()
        self.assertEqual(bad.send.await_count, 2)
        self.assertEqual(self.unsent(), 0)

    async def test_failed_send_keeps_the_alert_after_tracker_state_changes(self):
        cog = self.version_cog()
        self.channel.send.side_effect = self.failure()
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                versiontracker.constants, "VERSION_TRACKER_CHANNELS", {1: "ping"}
            ),
            self.assertLogs(utils.logger, level="ERROR"),
        ):
            await cog.poll()
            await self.bot.notifications.flush()
            await cog.poll()
        self.assertEqual(cog.data["version"], "new")
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.unsent(), 1)
        self.channel.send.side_effect = None
        await self.bot.notifications.flush(due_only=False)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertEqual(self.unsent(), 0)

    async def test_failed_send_is_retried_with_backoff(self):
        self.bot.get_channel.return_value = None
        await self.bot.database.save("test", {}, [utils.make_alert(1, "ping")])
        clock = [1000.0]
        attempts_at = []

        def get_channel(channel_id):
            attempts_at.append(clock[0])

        self.bot.get_channel.side_effect = get_channel
        outbox = self.bot.notifications
        with (
            patch.object(notifications.time, "time", side_effect=lambda: clock[0]),
            patch.object(utils.logger, "warning"),
        ):
            # Created at a real time, so set the clock just after it.
            clock[0] = (await self.bot.database.due_alerts(float("inf")))[0].created_at
            start = clock[0]
            for _ in range(10 * 60 * 4):
                await outbox.flush()
                clock[0] += 15
                if clock[0] - start > 3 * 60 * 60:
                    break
        gaps = [later - earlier for earlier, later in pairwise(attempts_at)]
        self.assertEqual(gaps[:7], [15, 30, 60, 120, 240, 480, 900])
        self.assertEqual(set(gaps[7:]), {900})

    async def test_alert_that_keeps_failing_is_dead_after_six_hours(self):
        self.bot.get_channel.return_value = None
        await self.bot.database.save("test", {}, [utils.make_alert(1, "ping")])
        created = (await self.bot.database.due_alerts(float("inf")))[0].created_at
        outbox = self.bot.notifications
        self.assertEqual(outbox.max_age, 6 * 60 * 60)
        with patch.object(utils.logger, "warning"):
            with patch.object(
                notifications.time, "time", return_value=created + 6 * 60 * 60 - 1
            ):
                await outbox.flush(due_only=False)
            self.assertEqual(self.rows(), [(1, None, 1, 0, 0)])
            with (
                patch.object(
                    notifications.time, "time", return_value=created + 6 * 60 * 60 + 1
                ),
                self.assertLogs(notifications.logger, level="ERROR"),
            ):
                await outbox.flush(due_only=False)
        self.assertEqual(self.rows(), [(1, None, 2, 0, 1)])
        self.bot.get_channel.return_value = self.channel
        await outbox.flush(due_only=False)
        self.channel.send.assert_not_awaited()

    async def test_unexpected_send_error_backs_off_without_blocking_the_channel(self):
        await self.bot.database.save(
            "test", {}, [utils.make_alert(1, "first"), utils.make_alert(1, "second")]
        )
        self.channel.send.side_effect = [OSError("connection reset"), Mock()]
        with self.assertLogs(notifications.logger, level="ERROR"):
            await self.bot.notifications.flush()
        self.assertEqual(self.rows(), [(1, None, 1, 0, 0), (1, None, 0, 1, 0)])
        await self.bot.notifications.flush()
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_concurrent_flushes_do_not_send_a_message_twice(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(*args, **kwargs):
            entered.set()
            await release.wait()
            return Mock(spec=disnake.Message)

        self.channel.send.side_effect = send
        await self.bot.database.save("test", {}, [utils.make_alert(1, "ping")])
        first = asyncio.create_task(self.bot.notifications.flush())
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(self.bot.notifications.flush(due_only=False))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.unsent(), 0)

    async def test_failed_sent_mark_is_retried_without_sending_again(self):
        await self.bot.database.save("test", {}, [utils.make_alert(1, "ping")])
        with patch.object(self.bot.database, "_update", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                await self.bot.notifications.flush()
        self.channel.send.assert_awaited_once()
        await self.bot.notifications.flush(due_only=False)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.unsent(), 0)

    async def test_saved_alerts_wake_the_sender(self):
        outbox = self.bot.notifications
        with patch.object(outbox, "poll_interval", 3600):
            task = asyncio.create_task(outbox.run())
            try:
                await asyncio.sleep(0.05)
                sent = asyncio.Event()

                async def send(*args, **kwargs):
                    sent.set()
                    return Mock(spec=disnake.Message)

                self.channel.send.side_effect = send
                await self.bot.database.save("test", {}, [utils.make_alert(1, "x")])
                await asyncio.wait_for(sent.wait(), 2)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_failed_auction_alert_save_keeps_the_scan_checkpoint_for_retry(self):
        cog = auctionhouse.AuctionTrackerCog(self.bot)
        cog.last_scanned_active = 100_000
        auction = {
            "uuid": "auction",
            "auctioneer": "a" * 32,
            "start": 150_000,
            "bin": True,
            "starting_bid": 1,
        }
        item = {"tag": {"ExtraAttributes": {"uuid": "item", "id": "CAKE_SOUL"}}}
        page = {"lastUpdated": 200_000, "auctions": [auction]}
        with (
            patch.object(auctionhouse, "get_active_auctions", return_value=page),
            patch.object(auctionhouse, "decode_items", return_value=[item]),
            patch.object(
                auctionhouse,
                "make_auction_embed",
                return_value=disnake.Embed(title="Soul"),
            ),
        ):
            with patch.object(self.bot.database, "_save", side_effect=OSError):
                with self.assertRaises(OSError):
                    await cog.active_scanner()
            self.assertEqual(cog.last_scanned_active, 100_000)
            await self.bot.notifications.flush()
            self.channel.send.assert_not_awaited()
            await cog.active_scanner()
        self.assertEqual(cog.last_scanned_active, 200_000)
        self.restart()
        self.assertEqual(
            auctionhouse.AuctionTrackerCog(self.bot).cursors["active"], 200_000
        )
        await self.bot.notifications.flush()
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.kwargs["embeds"][0].title, "Soul")
