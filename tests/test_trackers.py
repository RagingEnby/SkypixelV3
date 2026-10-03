import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from skypixel import app
from skypixel.storage.json import JsonWrapper
from skypixel.storage.mongo import flush_queue
from skypixel.trackers import (
    auctionhouse,
    firesaletracker,
    ranktracker,
    wikitracker,
)
from skypixel.trackers.base import PollingCog
from tests import support


class ProbeCog(PollingCog):
    async def poll(self):
        await asyncio.Future()


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_keeps_one_task(self):
        cog = ProbeCog(Mock())
        await cog.on_ready()
        task = cog.task
        await cog.on_ready()
        self.assertIs(cog.task, task)
        await cog.close()
        self.assertTrue(task.cancelled())
        self.assertIsNone(cog.task)

    async def test_close_waits_for_poll_cleanup(self):
        started, stopped = asyncio.Event(), asyncio.Event()
        cog = ProbeCog(Mock())

        async def poll():
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        async def close_resources():
            self.assertTrue(stopped.is_set())

        cog.poll = poll
        cog.close_resources = close_resources
        await cog.on_ready()
        await started.wait()
        await asyncio.wait_for(cog.close(), timeout=1)
        await cog.close()
        await cog.on_ready()
        self.assertIsNone(cog.task)

    async def test_poll_error_does_not_stop_the_tracker(self):
        cog = ProbeCog(Mock())
        cog._logger = Mock()
        complete = asyncio.Event()
        attempts = 0

        async def poll():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("bad response")
            complete.set()
            await asyncio.Future()

        cog.poll = poll
        with patch("skypixel.trackers.base.asyncio.sleep", new_callable=AsyncMock):
            await cog.on_ready()
            await asyncio.wait_for(complete.wait(), timeout=1)
            await cog.close()
        self.assertEqual(attempts, 2)
        cog._logger.exception.assert_called_once()

    def test_poll_intervals_match_the_existing_bot(self):
        expected = {
            "AlphaTrackerCog": 240,
            "FireSaleTrackerCog": 120,
            "JobTrackerCog": 1800,
            "MotdTrackerCog": 240,
            "RankTrackerCog": 240,
            "StatusUpdaterCog": 20,
            "VersionTrackerCog": 120,
            "WikiTrackerCog": 30,
            "ZoneTrackerCog": 12000,
        }
        cogs = {cog.__name__: cog for cog in app.load_cogs()}
        for name, interval in expected.items():
            self.assertEqual(cogs[name].interval, interval)


class RankCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_rank_response_does_not_replace_the_cache(self):
        cached = {"staff": [{"id": "abc", "name": "Player"}]}
        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", cached),
            patch.object(ranktracker, "RANK_LIST_CACHE_TIME", 0),
            patch.object(ranktracker, "time", SimpleNamespace(monotonic=lambda: 86401)),
            patch.object(ranktracker, "RANK_LIST_CACHE_LOCK", asyncio.Lock()),
            patch.object(
                ranktracker.http,
                "get_json",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            with self.assertRaises(ValueError):
                await ranktracker.get_rank_lists()
            self.assertEqual(ranktracker.RANK_LIST_CACHE, cached)

    async def test_concurrent_reads_fetch_once_and_do_not_mutate_the_cache(self):
        data = {"staff": [{"id": "abc", "name": "Player"}]}
        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", None),
            patch.object(ranktracker, "RANK_LIST_CACHE_TIME", 0.0),
            patch.object(ranktracker, "RANK_LIST_CACHE_LOCK", asyncio.Lock()),
            patch.object(
                ranktracker.http,
                "get_json",
                new_callable=AsyncMock,
                return_value=data,
            ) as fetch,
            patch.object(ranktracker, "edit_stat_channels", new_callable=AsyncMock),
        ):
            snapshots = await asyncio.gather(
                ranktracker.get_rank_lists(), ranktracker.get_rank_lists()
            )
            snapshots[0]["staff"][0]["name"] = "Changed"
            self.assertEqual(ranktracker.RANK_LIST_CACHE, data)
            self.assertEqual(snapshots[1]["staff"][0]["name"], "Player")
            self.assertNotIn("special", ranktracker.RANK_LIST_CACHE)
        fetch.assert_awaited_once()

    async def test_rank_cache_keeps_the_existing_24_hour_ttl(self):
        cached = {"staff": [{"id": "abc", "name": "Player"}]}
        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", cached),
            patch.object(ranktracker, "RANK_LIST_CACHE_TIME", 100.0),
            patch.object(
                ranktracker,
                "time",
                SimpleNamespace(monotonic=lambda: 100.0 + 86400 - 1),
            ),
            patch.object(ranktracker.http, "get_json", new_callable=AsyncMock) as fetch,
            patch.object(ranktracker, "edit_stat_channels", new_callable=AsyncMock),
        ):
            self.assertEqual(await ranktracker.get_rank_lists(), cached)
            fetch.assert_not_awaited()
            ranktracker.time.monotonic = lambda: 100.0 + 86400
            fetch.return_value = {"staff": []}
            self.assertEqual(await ranktracker.get_rank_lists(), {"staff": []})
            fetch.assert_awaited_once()

    async def test_channel_counts_do_not_add_a_synthetic_player_rank(self):
        data = {"innit": [{"id": "abc", "name": "Player"}]}
        with patch.object(ranktracker.constants, "BOT", None):
            await ranktracker.edit_stat_channels(data)
        self.assertEqual(set(data), {"innit"})

    async def test_watchlist_can_remove_more_than_one_player(self):
        state = JsonWrapper(support.TEST_STORAGE.name + "/watch-test.json")
        state.data = {"a": "old", "b": "old"}
        state.save = AsyncMock()
        with (
            patch.object(ranktracker, "WATCH_LIST", state),
            patch.object(
                ranktracker, "get_rankname", new_callable=AsyncMock, return_value="new"
            ),
        ):
            await ranktracker.RankTrackerCog.do_watchlist()
        self.assertEqual(state.to_dict(), {})
        self.assertEqual(state.save.await_count, 2)


class TrackerStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_active_upload_does_not_skip_ended_uploads(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        with (
            patch.object(cog.active_uploads, "flush", side_effect=OSError),
            patch.object(cog.ended_uploads, "flush", new_callable=AsyncMock) as flush,
        ):
            with self.assertRaises(OSError):
                await cog.upload_queue()
        flush.assert_awaited_once()

    async def test_failed_active_close_does_not_skip_the_ended_collection(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        with (
            patch.object(cog.active_uploads, "close", side_effect=OSError),
            patch.object(cog.ended_uploads, "close", new_callable=AsyncMock) as close,
        ):
            with self.assertRaises(OSError):
                await cog.close_resources()
        close.assert_awaited_once()

    async def test_auction_failure_waits_for_other_tasks(self):
        completed = False

        async def fail():
            raise OSError("failed request")

        async def complete():
            nonlocal completed
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            completed = True

        with self.assertRaises(OSError):
            await auctionhouse.finish_tasks(fail(), complete())
        self.assertTrue(completed)

    async def test_auction_poll_uploads_the_successful_scanner_after_a_failure(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())

        async def scan_ended():
            await asyncio.sleep(0)
            cog.ended_uploads.append({"_id": "ended"})
            return 30.0

        async def upload():
            self.assertEqual(cog.ended_uploads.docs, [{"_id": "ended"}])

        with (
            patch.object(
                cog, "active_scanner", new_callable=AsyncMock, side_effect=OSError
            ),
            patch.object(cog, "ended_scanner", side_effect=scan_ended),
            patch.object(cog, "upload_queue", side_effect=upload) as flush,
        ):
            with self.assertRaises(OSError):
                await cog.poll()
        flush.assert_awaited_once()

    async def test_first_fire_sale_poll_saves_without_notifications(self):
        cog = firesaletracker.FireSaleTrackerCog(Mock())
        cog.data.data = {}
        cog.data.save = AsyncMock()
        sales = {"ONE": {"amount": 1}, "TWO": {"amount": 2}}
        with (
            patch.object(
                firesaletracker,
                "get_fire_sales",
                new_callable=AsyncMock,
                return_value=sales,
            ),
            patch.object(firesaletracker, "send", new_callable=AsyncMock) as send,
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
        ):
            await cog.poll()
        send.assert_not_awaited()
        cog.data.save.assert_awaited_once()
        self.assertEqual(cog.data.to_dict(), sales)

    async def test_first_wiki_poll_seeds_all_edits_without_notifications(self):
        cog = wikitracker.WikiTrackerCog(Mock())
        cog.data.data = {"edits": []}
        cog.data.save = AsyncMock()
        edits = [
            {"type": "edit", "revid": 1},
            {"type": "new", "revid": 2},
            {"type": "edit", "revid": 2},
        ]
        with (
            patch.object(
                wikitracker, "get_edits", new_callable=AsyncMock, return_value=edits
            ),
            patch.object(cog, "on_wiki_edit", new_callable=AsyncMock) as notify,
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
        ):
            await cog.poll()
        notify.assert_not_awaited()
        self.assertEqual(cog.data["edits"], [1, 2])

    async def test_queue_keeps_records_added_during_upload(self):
        queue = [{"_id": "first"}]
        uploaded = []

        async def update(docs):
            uploaded.extend(docs)
            if docs[0]["_id"] == "first":
                queue.append({"_id": "second"})

        await flush_queue(Mock(update_many=AsyncMock(side_effect=update)), queue)
        self.assertEqual(uploaded, [{"_id": "first"}, {"_id": "second"}])
        self.assertEqual(queue, [])

    async def test_failed_upload_retains_the_queue(self):
        queue = [{"_id": "first"}]
        with self.assertRaises(OSError):
            await flush_queue(Mock(update_many=AsyncMock(side_effect=OSError)), queue)
        self.assertEqual(queue, [{"_id": "first"}])

    async def test_auction_fetch_rejects_a_malformed_response(self):
        with patch.object(
            auctionhouse.http,
            "get_json",
            new_callable=AsyncMock,
            return_value={"success": False},
        ):
            with self.assertRaises(ValueError):
                await auctionhouse.get_active_auctions()

    async def test_bad_auction_does_not_stop_the_batch(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        with (
            patch.object(
                cog,
                "on_auction",
                new_callable=AsyncMock,
                side_effect=[ValueError("bad item"), None],
            ) as process,
            self.assertLogs(auctionhouse.logger, level="ERROR"),
        ):
            await asyncio.gather(
                cog.process_auction({"uuid": "bad"}),
                cog.process_auction({"uuid": "good"}),
            )
        self.assertEqual(process.await_count, 2)
