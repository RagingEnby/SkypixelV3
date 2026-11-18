# pyright: reportPrivateUsage=false
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock, patch

import disnake

from skypixel import constants, subscriptions, utils
from skypixel.storage.notifications import NotificationOutbox, NotificationStorageError
from skypixel.trackers import auctionhouse, versiontracker

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot
    from skypixel.storage.notifications import PendingMessage


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_storage_failure_keeps_successful_delivery_across_restart(
        self,
    ) -> None:
        first = self.channel
        second = Mock(spec=disnake.TextChannel)
        second.send = AsyncMock(return_value=Mock(spec=disnake.Message))

        def get_channel(channel_id: int) -> Mock:
            return first if channel_id == 1 else second

        self.bot.get_channel.side_effect = get_channel
        original = self.bot.notifications.pending.set_and_save

        async def save(key: str, message: PendingMessage) -> None:
            if message["channel_id"] == 2:
                raise OSError("disk full")
            await original(key, message)

        footers = sorted(constants.CREDIT_FOOTERS)
        embed = disnake.Embed(title="Alert").set_footer(text=footers[0])
        with patch.object(
            self.bot.notifications.pending, "set_and_save", side_effect=save
        ):
            with self.assertRaises(NotificationStorageError):
                await utils.broadcast(
                    self.client, {1: "first", 2: "second"}, embed=embed
                )
        first.send.assert_awaited_once()
        second.send.assert_not_awaited()
        self.bot.notifications = NotificationOutbox(self.client, self.path)
        embed.set_footer(text=footers[-1])
        await utils.broadcast(self.client, {1: "first", 2: "second"}, embed=embed)
        first.send.assert_awaited_once()
        second.send.assert_awaited_once()
        self.assertFalse(self.bot.notifications.pending)
        self.assertFalse(self.bot.notifications.events)

    async def test_failed_receipt_save_retries_the_save_without_sending_again(
        self,
    ) -> None:
        with patch.object(self.bot.notifications.events, "save", side_effect=OSError):
            with self.assertRaises(NotificationStorageError):
                await utils.broadcast(
                    self.client, {1: "ping"}, embed=disnake.Embed(title="Alert")
                )
        self.channel.send.assert_awaited_once()
        await utils.broadcast(
            self.client, {1: "ping"}, embed=disnake.Embed(title="Alert")
        )
        self.channel.send.assert_awaited_once()
        self.assertFalse(self.bot.notifications.pending)
        self.assertFalse(self.bot.notifications.events)

    async def test_tracker_state_save_failure_reuses_receipts_but_a_later_event_sends_again(
        self,
    ) -> None:
        cog = versiontracker.VersionTrackerCog(self.client)
        cog.data.data = {"version": "old"}
        with (
            patch.object(
                versiontracker, "get_version", side_effect=["new", "new", "old", "new"]
            ),
            patch.object(
                subscriptions,
                "_current",
                subscriptions.Subscriptions(version={1: "ping"}),
            ),
        ):
            with patch.object(cog.data, "replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    await cog.poll()
            self.channel.send.assert_awaited_once()
            self.assertEqual(cog.data["version"], "old")
            self.bot.notifications = NotificationOutbox(self.client, self.path)
            await cog.poll()
            self.channel.send.assert_awaited_once()
            await cog.poll()
            await cog.poll()
        self.assertEqual(self.channel.send.await_count, 3)
        self.assertEqual(cog.data["version"], "new")
        self.assertFalse(self.bot.notifications.events)

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "notifications.json"
        self.channel = Mock(spec=disnake.TextChannel)
        self.channel.send = AsyncMock(return_value=Mock(spec=disnake.Message))
        self.bot = SimpleNamespace(
            get_channel=Mock(return_value=self.channel),
            settings=SimpleNamespace(
                storage_dir=Path(self.directory.name), mongodb_uri="mongodb://localhost"
            ),
        )
        # The fake bot stands in for a SkypixelBot in the code under test.
        self.client = cast("SkypixelBot", self.bot)
        self.bot.notifications = NotificationOutbox(self.client, self.path)

    def failure(self) -> disnake.HTTPException:
        return disnake.HTTPException(Mock(status=503, reason="Unavailable"), "failure")

    async def test_failed_alert_survives_restart_and_retries_with_its_thread(
        self,
    ) -> None:
        self.bot.get_channel.return_value = None
        with self.assertLogs(utils.logger, level="WARNING"):
            await utils.notify_to_channel(
                self.client, 1, "ping", thread_id=2, embed=disnake.Embed(title="Alert")
            )
        self.assertEqual(len(self.bot.notifications.pending), 1)
        self.bot.notifications = NotificationOutbox(self.client, self.path)
        self.channel.get_thread.return_value = self.channel
        self.bot.get_channel.return_value = self.channel
        await self.bot.notifications.flush()
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.args, ("ping",))
        self.assertEqual(self.channel.send.call_args.kwargs["embeds"][0].title, "Alert")
        self.assertFalse(self.bot.notifications.pending)
        self.assertFalse(NotificationOutbox(self.client, self.path).pending)

    async def test_broadcast_retries_only_the_failed_destination(self) -> None:
        good = self.channel
        bad = Mock(spec=disnake.TextChannel)
        bad.send = AsyncMock(side_effect=[self.failure(), Mock(spec=disnake.Message)])

        def get_channel(channel_id: int) -> Mock:
            return good if channel_id == 1 else bad

        self.bot.get_channel.side_effect = get_channel
        with self.assertLogs(utils.logger, level="ERROR"):
            await utils.broadcast(
                self.client,
                {1: "first", 2: "second"},
                embed=disnake.Embed(title="Alert"),
            )
        self.assertEqual(len(self.bot.notifications.pending), 1)
        await self.bot.notifications.flush()
        good.send.assert_awaited_once()
        self.assertEqual(bad.send.await_count, 2)
        self.assertFalse(self.bot.notifications.pending)

    async def test_failed_send_keeps_the_alert_after_tracker_state_changes(
        self,
    ) -> None:
        cog = versiontracker.VersionTrackerCog(self.client)
        cog.data.data = {"version": "old"}
        self.channel.send.side_effect = self.failure()
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                subscriptions,
                "_current",
                subscriptions.Subscriptions(version={1: "ping"}),
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

    async def test_failed_outbox_save_prevents_tracker_state_changes(self) -> None:
        cog = versiontracker.VersionTrackerCog(self.client)
        cog.data.data = {"version": "old"}
        with (
            patch.object(versiontracker, "get_version", return_value="new"),
            patch.object(
                subscriptions,
                "_current",
                subscriptions.Subscriptions(version={1: "ping"}),
            ),
            patch.object(
                self.bot.notifications.pending, "set_and_save", side_effect=OSError
            ),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
        self.assertEqual(cog.data["version"], "old")
        self.channel.send.assert_not_awaited()

    async def test_concurrent_retry_and_submission_do_not_send_a_message_twice(
        self,
    ) -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(*args: object, **kwargs: object) -> Mock:
            entered.set()
            await release.wait()
            return Mock(spec=disnake.Message)

        self.channel.send.side_effect = send
        submit = asyncio.create_task(utils.notify_to_channel(self.client, 1, "ping"))
        await asyncio.wait_for(entered.wait(), 1)
        retry = asyncio.create_task(self.bot.notifications.flush())
        release.set()
        await asyncio.gather(submit, retry)
        self.channel.send.assert_awaited_once()
        self.assertFalse(self.bot.notifications.pending)

    async def test_failed_auction_alert_save_keeps_the_scan_checkpoint_for_retry(
        self,
    ) -> None:
        cog = auctionhouse.AuctionTrackerCog(self.client)
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
            with patch.object(
                self.bot.notifications.pending, "set_and_save", side_effect=OSError
            ):
                with self.assertRaises(NotificationStorageError):
                    await cog.active_scanner()
            self.assertEqual(cog.last_scanned_active, 100_000)
            self.channel.send.assert_not_awaited()
            await cog.active_scanner()
        self.assertEqual(cog.last_scanned_active, 200_000)
        self.channel.send.assert_awaited_once()

    async def test_run_waits_before_it_retries_a_failed_alert(self) -> None:
        self.bot.get_channel.return_value = None
        with self.assertLogs(utils.logger, level="WARNING"):
            await utils.notify_to_channel(
                self.client, 1, embed=disnake.Embed(title="A")
            )
        self.bot.get_channel.return_value = self.channel
        await self.bot.notifications.flush(due_only=True)
        self.channel.send.assert_not_awaited()
        self.bot.notifications._retry_at.clear()
        await self.bot.notifications.flush(due_only=True)
        self.channel.send.assert_awaited_once()
        self.assertFalse(self.bot.notifications.pending)

    async def test_alert_that_keeps_failing_is_dropped_after_the_age_limit(
        self,
    ) -> None:
        self.bot.get_channel.return_value = None
        outbox: NotificationOutbox = self.bot.notifications
        with self.assertLogs(utils.logger, level="WARNING"):
            await utils.notify_to_channel(
                self.client, 1, embed=disnake.Embed(title="A")
            )
        self.assertEqual(len(outbox.pending), 1)
        with (
            patch.object(outbox, "max_age", -1),
            self.assertLogs("skypixel.storage.notifications", level="ERROR"),
        ):
            await outbox.flush()
        self.assertFalse(outbox.pending)
        self.assertFalse(outbox.events)

    async def test_alert_saved_without_an_age_is_retried_and_not_dropped(self) -> None:
        self.bot.get_channel.return_value = None
        outbox: NotificationOutbox = self.bot.notifications
        with self.assertLogs(utils.logger, level="WARNING"):
            await utils.notify_to_channel(
                self.client, 1, embed=disnake.Embed(title="A")
            )
        key = next(iter(outbox.pending))
        legacy = {k: v for k, v in outbox.pending[key].items() if k != "created_at"}
        # An old record has no created_at field, so it does not match the type.
        await outbox.pending.set_and_save(key, cast("PendingMessage", legacy))
        with self.assertLogs(utils.logger, level="WARNING"):
            await outbox.flush()
        self.assertIn("created_at", outbox.pending[key])
        self.bot.get_channel.return_value = self.channel
        await outbox.flush()
        self.channel.send.assert_awaited_once()
        self.assertFalse(outbox.pending)
