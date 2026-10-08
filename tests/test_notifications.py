import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import disnake

from skypixel import utils
from skypixel.storage.notifications import NotificationOutbox
from skypixel.trackers import versiontracker


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "notifications.json"
        self.channel = Mock(spec=disnake.TextChannel)
        self.channel.send = AsyncMock(return_value=Mock(spec=disnake.Message))
        self.bot = SimpleNamespace(
            get_channel=Mock(return_value=self.channel),
            settings=SimpleNamespace(storage_dir=Path(self.directory.name)),
        )
        self.bot.notifications = NotificationOutbox(self.bot, self.path)

    def failure(self):
        return disnake.HTTPException(Mock(status=503, reason="Unavailable"), "failure")

    async def test_failed_alert_survives_restart_and_retries_with_its_thread(self):
        self.bot.get_channel.return_value = None
        with self.assertLogs(utils.logger, level="WARNING"):
            await utils.notify_to_channel(
                self.bot, 1, "ping", thread_id=2, embed=disnake.Embed(title="Alert")
            )
        self.assertEqual(len(self.bot.notifications.pending), 1)
        self.bot.notifications = NotificationOutbox(self.bot, self.path)
        self.channel.get_thread.return_value = self.channel
        self.bot.get_channel.return_value = self.channel
        await self.bot.notifications.flush()
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.args, ("ping",))
        self.assertEqual(self.channel.send.call_args.kwargs["embeds"][0].title, "Alert")
        self.assertFalse(self.bot.notifications.pending)
        self.assertFalse(NotificationOutbox(self.bot, self.path).pending)

    async def test_broadcast_retries_only_the_failed_destination(self):
        good = self.channel
        bad = Mock(spec=disnake.TextChannel)
        bad.send = AsyncMock(side_effect=[self.failure(), Mock(spec=disnake.Message)])
        self.bot.get_channel.side_effect = lambda channel_id: (
            good if channel_id == 1 else bad
        )
        with self.assertLogs(utils.logger, level="ERROR"):
            await utils.broadcast(
                self.bot, {1: "first", 2: "second"}, embed=disnake.Embed(title="Alert")
            )
        self.assertEqual(len(self.bot.notifications.pending), 1)
        await self.bot.notifications.flush()
        good.send.assert_awaited_once()
        self.assertEqual(bad.send.await_count, 2)
        self.assertFalse(self.bot.notifications.pending)

    async def test_failed_send_keeps_the_alert_after_tracker_state_changes(self):
        cog = versiontracker.VersionTrackerCog(self.bot)
        cog.data.data = {"version": "old"}
        self.channel.send.side_effect = self.failure()
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                versiontracker.constants, "VERSION_TRACKER_CHANNELS", {1: "ping"}
            ),
            self.assertLogs(utils.logger, level="ERROR"),
        ):
            await cog.poll()
            await cog.poll()
        self.assertEqual(cog.data["version"], "new")
        self.channel.send.assert_awaited_once()
        self.assertEqual(len(self.bot.notifications.pending), 1)
        self.channel.send.side_effect = None
        await self.bot.notifications.flush()
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertFalse(self.bot.notifications.pending)

    async def test_failed_outbox_save_prevents_tracker_state_changes(self):
        cog = versiontracker.VersionTrackerCog(self.bot)
        cog.data.data = {"version": "old"}
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                versiontracker.constants, "VERSION_TRACKER_CHANNELS", {1: "ping"}
            ),
            patch.object(
                self.bot.notifications.pending, "set_and_save", side_effect=OSError
            ),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
        self.assertEqual(cog.data["version"], "old")
        self.channel.send.assert_not_awaited()

    async def test_concurrent_retry_and_submission_do_not_send_a_message_twice(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(*args, **kwargs):
            entered.set()
            await release.wait()
            return Mock(spec=disnake.Message)

        self.channel.send.side_effect = send
        submit = asyncio.create_task(utils.notify_to_channel(self.bot, 1, "ping"))
        await asyncio.wait_for(entered.wait(), 1)
        retry = asyncio.create_task(self.bot.notifications.flush())
        release.set()
        await asyncio.gather(submit, retry)
        self.channel.send.assert_awaited_once()
        self.assertFalse(self.bot.notifications.pending)
