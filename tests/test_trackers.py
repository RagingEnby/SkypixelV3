import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from curl_cffi.requests.exceptions import HTTPError

import tests.support as support
from skypixel import app
from skypixel.storage.json_store import JsonWrapper
from skypixel.storage.mongo import flush_queue
from skypixel.trackers import (
    auctionhouse,
    firesaletracker,
    jobtracker,
    ranktracker,
)
from skypixel.trackers.base import PollingCog
from skypixel.trackers.status import StatusUpdaterCog


class ProbeCog(PollingCog):
    async def poll(self):
        await asyncio.Future()


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_rank_status_uses_cached_special_rank_lists(self):
        bot = Mock(change_presence=AsyncMock(), guilds=[])
        cog = StatusUpdaterCog(bot)
        players = [{"id": "one", "name": "One"}, {"id": "two", "name": "Two"}]
        with (
            patch.object(
                ranktracker, "get_rank_lists", return_value={"staff": players}
            ),
            patch.object(
                ranktracker, "get_rank_counts", new_callable=AsyncMock
            ) as counts,
        ):
            await cog._rank_status("staff")
        counts.assert_not_awaited()
        activity = bot.change_presence.await_args.kwargs["activity"]
        self.assertEqual(activity.state, "Tracking 2 [STAFF] players")

    async def test_rank_status_handles_an_empty_special_rank(self):
        bot = Mock(change_presence=AsyncMock(), guilds=[])
        cog = StatusUpdaterCog(bot)
        with patch.object(ranktracker, "get_rank_lists", return_value={"staff": []}):
            await cog._rank_status("youtube")
        activity = bot.change_presence.await_args.kwargs["activity"]
        self.assertEqual(activity.state, "Tracking 0 [YOUTUBE] players")

    async def test_status_failure_does_not_stop_the_rotation(self):
        bot = Mock(change_presence=AsyncMock(), guilds=[])
        cog = StatusUpdaterCog(bot)
        cog.index = 2
        with patch.object(cog, "_rank_status", side_effect=[OSError, None]) as rank:
            with self.assertRaises(OSError):
                await cog.poll()
            await cog.poll()
        self.assertEqual(
            [call.args[0] for call in rank.await_args_list], ["staff", "youtube"]
        )
        cog.index = 15
        with patch.object(cog, "_item_count_status", new_callable=AsyncMock):
            await cog.poll()
        self.assertEqual(cog.index, 0)
        await cog.poll()
        bot.change_presence.assert_awaited_once()

    async def test_reconnect_keeps_one_task(self):
        cog = ProbeCog(support.make_bot())
        await cog.on_ready()
        task = cog.task
        await cog.on_ready()
        self.assertIs(cog.task, task)
        await cog.close()
        self.assertTrue(task.cancelled())
        self.assertIsNone(cog.task)

    async def test_close_waits_for_poll_cleanup(self):
        started, stopped = asyncio.Event(), asyncio.Event()
        cog = ProbeCog(support.make_bot())

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
        cog = ProbeCog(support.make_bot())
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
            "ZoneTrackerCog": 12000,
        }
        cogs = {cog.__name__: cog for cog in app.load_cogs()}
        for name, interval in expected.items():
            self.assertEqual(cogs[name].interval, interval)


class RankCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_rank_lookup_keeps_the_player_lists(self):
        response = Mock(json=Mock(return_value={"rankname": "[ADMIN] Player"}))
        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", {"staff": []}),
            patch.object(ranktracker.http, "get", return_value=response),
        ):
            self.assertEqual(await ranktracker.get_rankname("Player"), "[ADMIN] Player")
            self.assertEqual(ranktracker.RANK_LIST_CACHE, {"staff": []})

    async def test_unchanged_watchlist_keeps_the_player_lists(self):
        state = JsonWrapper(support.TEST_STORAGE.name + "/watch-same.json")
        state.data = {"a": "same"}
        cog = ranktracker.RankTrackerCog(support.make_bot())
        cog.watch_list = state
        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", {"staff": []}),
            patch.object(
                ranktracker, "get_rankname", new_callable=AsyncMock, return_value="same"
            ),
        ):
            await cog.do_watchlist()
            self.assertEqual(ranktracker.RANK_LIST_CACHE, {"staff": []})

    async def test_rate_limit_stops_the_watchlist_without_changing_players(self):
        state = JsonWrapper(support.TEST_STORAGE.name + "/watch-limited.json")
        state.data = {"first": "same", "second": "same"}
        cog = ranktracker.RankTrackerCog(support.make_bot())
        cog.watch_list = state
        error = HTTPError("Rate limited", response=Mock(status_code=429))
        with patch.object(
            ranktracker, "get_rankname", new_callable=AsyncMock, side_effect=error
        ) as get:
            await cog.do_watchlist()
        get.assert_awaited_once_with("first")
        self.assertEqual(state.data, {"first": "same", "second": "same"})

    async def test_invalidation_during_a_fetch_expires_the_fetched_lists(self):
        data = {"staff": [{"id": "abc", "name": "Player"}]}

        async def fetch(url):
            ranktracker.invalidate_rank_lists()
            return data

        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", None),
            patch.object(ranktracker, "RANK_LIST_GENERATION", 0),
            patch.object(ranktracker, "RANK_LIST_CACHE_LOCK", asyncio.Lock()),
            patch.object(ranktracker.http, "get_json", side_effect=fetch) as get,
            patch.object(ranktracker, "edit_stat_channels", new_callable=AsyncMock),
        ):
            self.assertEqual(await ranktracker.get_rank_lists(), data)
            await ranktracker.get_rank_lists()
        self.assertEqual(get.await_count, 2)

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

    async def test_rank_cache_expires_after_its_ttl(self):
        cached = {"staff": [{"id": "abc", "name": "Player"}]}
        ttl = ranktracker.RANK_LIST_CACHE_TTL_SECONDS
        with (
            patch.object(ranktracker, "RANK_LIST_CACHE", cached),
            patch.object(ranktracker, "RANK_LIST_CACHE_TIME", 100.0),
            patch.object(
                ranktracker,
                "time",
                SimpleNamespace(monotonic=lambda: 100.0 + ttl - 1),
            ),
            patch.object(ranktracker.http, "get_json", new_callable=AsyncMock) as fetch,
            patch.object(ranktracker, "edit_stat_channels", new_callable=AsyncMock),
        ):
            self.assertEqual(await ranktracker.get_rank_lists(), cached)
            fetch.assert_not_awaited()
            ranktracker.time.monotonic = lambda: 100.0 + ttl
            fetch.return_value = {"staff": []}
            self.assertEqual(await ranktracker.get_rank_lists(), {"staff": []})
            fetch.assert_awaited_once()

    async def test_channel_counts_do_not_add_a_synthetic_player_rank(self):
        data = {"innit": [{"id": "abc", "name": "Player"}]}
        bot = Mock(get_channel=Mock(return_value=None))
        with self.assertLogs(ranktracker.logger, level="ERROR"):
            await ranktracker.edit_stat_channels(bot, data)
        self.assertEqual(set(data), {"innit"})

    async def test_watchlist_can_remove_more_than_one_player(self):
        state = JsonWrapper(support.TEST_STORAGE.name + "/watch-test.json")
        state.data = {"a": "old", "b": "old"}
        state.remove_and_save = AsyncMock(wraps=state.remove_and_save)
        cog = ranktracker.RankTrackerCog(support.make_bot())
        cog.watch_list = state
        with (
            patch.object(
                ranktracker, "get_rankname", new_callable=AsyncMock, return_value="new"
            ),
        ):
            await cog.do_watchlist()
        self.assertEqual(state.to_dict(), {})
        self.assertEqual(state.remove_and_save.await_count, 2)


class TrackerStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_fire_sale_save_keeps_the_sale_for_retry(self):
        cog = firesaletracker.FireSaleTrackerCog(support.make_bot())
        cog.data.data = {"OLD": {"amount": 1}}
        with (
            patch.object(firesaletracker, "get_fire_sales", return_value={"NEW": {}}),
            patch.object(cog, "make_fire_sale_embed", return_value=Mock()),
            patch.object(firesaletracker, "send", new_callable=AsyncMock),
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
            patch(
                "skypixel.storage.json_store.write_json", side_effect=[OSError, None]
            ),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            self.assertNotIn("NEW", cog.data)
            await cog.poll()
        self.assertIn("NEW", cog.data)

    async def test_rank_change_retries_only_the_failed_notifications(self):
        cog = ranktracker.RankTrackerCog(support.make_bot())
        before = {"player": {"name": "Before", "rank": "youtube"}}
        after = {"player": {"name": "After", "rank": "staff"}}
        cog.data.data = before
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
        with (
            patch.object(ranktracker.RankTrackerCog, "do_watchlist", AsyncMock()),
            patch.object(ranktracker, "get_player_ranks", return_value=after),
            patch.object(cog, "on_rank_change", new_callable=AsyncMock) as change,
            patch.object(
                cog, "on_name_change", side_effect=[OSError("send failed"), None]
            ) as rename,
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            self.assertEqual(cog.data.to_dict(), before)
            await cog.poll()
        change.assert_awaited_once_with("player", "After", "youtube", "staff")
        self.assertEqual(rename.await_count, 2)
        self.assertEqual(cog.data.to_dict(), after)
        self.assertEqual(cog.known_changes, set())

    async def test_unchanged_rank_lists_do_not_rewrite_the_state_file(self):
        cog = ranktracker.RankTrackerCog(support.make_bot())
        ranks = {"player": {"name": "Name", "rank": "youtube"}}
        cog.data.data = ranks
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
        with (
            patch.object(ranktracker.RankTrackerCog, "do_watchlist", AsyncMock()),
            patch.object(
                ranktracker,
                "get_player_ranks",
                return_value={"player": {"name": "Name", "rank": "youtube"}},
            ),
            patch.object(cog, "update_stat_channels", new_callable=AsyncMock) as stats,
        ):
            await cog.poll()
        cog.data.replace.assert_not_awaited()
        stats.assert_awaited_once()
        self.assertEqual(cog.data.to_dict(), ranks)

    async def test_fire_sale_notification_failure_keeps_the_sale_for_retry(self):
        cog = firesaletracker.FireSaleTrackerCog(support.make_bot())
        cog.data.data = {"OLD": {"amount": 1}}
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
        sales = {"NEW": {"amount": 2}}
        with (
            patch.object(firesaletracker, "get_fire_sales", return_value=sales),
            patch.object(cog, "make_fire_sale_embed", return_value=Mock()),
            patch.object(firesaletracker, "send", side_effect=[OSError, None]) as send,
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            self.assertNotIn("NEW", cog.data)
            await cog.poll()
        self.assertEqual(send.await_count, 2)
        self.assertEqual(cog.data["NEW"], sales["NEW"])

    async def test_failed_active_upload_does_not_skip_ended_uploads(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        with (
            patch.object(cog.active_uploads, "flush", side_effect=OSError),
            patch.object(cog.ended_uploads, "flush", new_callable=AsyncMock) as flush,
        ):
            with self.assertRaises(OSError):
                await cog.upload_queue()
        flush.assert_awaited_once()

    async def test_failed_active_close_does_not_skip_the_ended_collection(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
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
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())

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
        cog = firesaletracker.FireSaleTrackerCog(support.make_bot())
        cog.initialized = False
        cog.data.data = {}
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
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
        cog.data.replace.assert_awaited_once()
        self.assertEqual(cog.data.to_dict(), sales)

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
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
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
                cog.process_auction({"uuid": "bad"}, {}),
                cog.process_auction({"uuid": "good"}, {}),
            )
        self.assertEqual(process.await_count, 2)

    async def test_failed_alert_does_not_repeat_the_scanned_auctions(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        cog.last_scanned_active = 1000
        auctions = [
            {"uuid": "a", "start": 1500, "item_bytes": ""},
            {"uuid": "b", "start": 1500, "item_bytes": ""},
        ]
        pages = [
            {"lastUpdated": 2000, "auctions": auctions},
            {"lastUpdated": 3000, "auctions": auctions},
        ]
        with (
            patch.object(auctionhouse, "get_active_auctions", side_effect=pages),
            patch.object(auctionhouse, "decode_single", return_value={}),
            patch.object(
                cog,
                "on_auction",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("player lookup failed"), None],
            ) as process,
            self.assertLogs(auctionhouse.logger, level="ERROR"),
        ):
            await cog.active_scanner()
            await cog.active_scanner()
        self.assertEqual(process.await_count, 2)
        self.assertEqual(cog.last_scanned_active, 3000)

    async def test_upload_failure_keeps_the_scanner_schedule(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        with (
            patch.object(cog, "active_scanner", return_value=40.0),
            patch.object(cog, "ended_scanner", return_value=30.0),
            patch.object(cog, "upload_queue", side_effect=OSError),
            self.assertLogs(auctionhouse.logger, level="ERROR"),
        ):
            self.assertEqual(await cog.poll(), 30.0)

    async def test_late_auction_api_backs_off_until_it_updates(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        with patch.object(auctionhouse.time, "time", return_value=1000.0):
            self.assertEqual(cog.next_delay("active", 950_000, False), 10.0)
            delays = [cog.next_delay("active", 900_000, False) for _ in range(6)]
            self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0, 16.0])
            self.assertEqual(cog.next_delay("ended", 900_000, False), 1.0)
            self.assertEqual(cog.next_delay("active", 900_000, True), 1.0)

    async def test_rank_list_that_shrinks_by_half_needs_confirmation(self):
        cog = ranktracker.RankTrackerCog(support.make_bot())
        before = {str(i): {"name": f"P{i}", "rank": "youtube"} for i in range(6)}
        after = {"0": {"name": "P0", "rank": "youtube"}}
        cog.data.data = before
        with (
            patch.object(ranktracker.RankTrackerCog, "do_watchlist", AsyncMock()),
            patch.object(ranktracker, "get_player_ranks", return_value=after),
            patch.object(ranktracker, "invalidate_rank_lists") as invalidate,
            patch.object(cog, "on_rank_remove", new_callable=AsyncMock) as remove,
            patch("skypixel.storage.json_store.write_json", new_callable=AsyncMock),
            self.assertLogs(ranktracker.logger, level="ERROR"),
        ):
            await cog.poll()
            await cog.poll()
            remove.assert_not_awaited()
            self.assertEqual(invalidate.call_count, 2)
            await cog.poll()
        self.assertEqual(remove.await_count, 5)
        self.assertEqual(cog.data.to_dict(), after)
        self.assertEqual(cog.shrunken_polls, 0)

    async def test_small_rank_changes_do_not_need_confirmation(self):
        before = {str(i): {"name": f"P{i}", "rank": "youtube"} for i in range(6)}
        after = {key: value for key, value in before.items() if key != "0"}
        self.assertEqual(ranktracker.shrunken_ranks(before, after), [])
        self.assertEqual(
            ranktracker.shrunken_ranks({"a": {"name": "A", "rank": "mojang"}}, {}), []
        )


class JobTrackerTests(unittest.IsolatedAsyncioTestCase):
    def job(self, title):
        return jobtracker.Job(title, 1, ["q"], None, ["o"])

    async def test_empty_job_list_needs_confirmation(self):
        cog = jobtracker.JobTrackerCog(support.make_bot())
        cog.data.data = {"Dev": self.job("Dev").to_dict()}
        with (
            patch.object(jobtracker, "get_jobs", return_value=[]),
            patch.object(cog, "on_job_update", new_callable=AsyncMock) as notify,
            patch("skypixel.storage.json_store.write_json", new_callable=AsyncMock),
            self.assertLogs(jobtracker.logger, level="WARNING"),
        ):
            await cog.poll()
            await cog.poll()
            notify.assert_not_awaited()
            await cog.poll()
        notify.assert_awaited_once()
        self.assertEqual(cog.data.to_dict(), {})

    async def test_first_run_saves_jobs_without_notifications(self):
        cog = jobtracker.JobTrackerCog(support.make_bot())
        cog.data.data = {}
        cog.initialized = False
        with (
            patch.object(jobtracker, "get_jobs", return_value=[self.job("Dev")]),
            patch.object(cog, "on_job_update", new_callable=AsyncMock) as notify,
            patch("skypixel.storage.json_store.write_json", new_callable=AsyncMock),
        ):
            await cog.poll()
        notify.assert_not_awaited()
        self.assertIn("Dev", cog.data)
        self.assertTrue(cog.initialized)

    async def test_new_job_after_an_empty_saved_list_is_announced(self):
        cog = jobtracker.JobTrackerCog(support.make_bot())
        cog.data.data = {}
        cog.initialized = True
        with (
            patch.object(jobtracker, "get_jobs", return_value=[self.job("Dev")]),
            patch.object(cog, "on_job_update", new_callable=AsyncMock) as notify,
            patch("skypixel.storage.json_store.write_json", new_callable=AsyncMock),
        ):
            await cog.poll()
        notify.assert_awaited_once()

    async def test_invalid_rank_lookup_never_reaches_the_api(self):
        with patch.object(ranktracker.http, "get", new_callable=AsyncMock) as fetch:
            with self.assertRaises(ranktracker.mojang.PlayerNotFound):
                await ranktracker.get_rankname("../ranks")
        fetch.assert_not_awaited()

    async def test_full_watchlist_rejects_new_players(self):
        state = JsonWrapper(support.TEST_STORAGE.name + "/watch-full.json")
        state.data = {"a": None}
        cog = ranktracker.RankTrackerCog(support.make_bot())
        cog.watch_list = state
        inter = support.make_inter()
        with (
            patch.object(ranktracker, "WATCH_LIST_LIMIT", 1),
            patch.object(
                ranktracker.mojang,
                "get",
                new_callable=AsyncMock,
                return_value=Mock(id="b", name="Player"),
            ),
        ):
            await cog.watch.callback(cog, inter, "Player")
        self.assertEqual(state.to_dict(), {"a": None})
        self.assertEqual(support.error_title(inter), "Watchlist Full!")

    async def test_auction_items_decode_off_the_event_loop(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        loop_thread = threading.get_ident()
        threads = []

        def decode(item_bytes):
            threads.append(threading.get_ident())
            return {}

        cog.last_scanned_ended = 1000
        auctions = [
            {"auction_id": "a", "item_bytes": "", "timestamp": 1500},
            {"auction_id": "b", "item_bytes": "", "timestamp": 1500},
        ]
        with (
            patch.object(
                auctionhouse,
                "get_ended_auctions",
                return_value={"lastUpdated": 2000, "auctions": auctions},
            ),
            patch.object(auctionhouse, "decode_single", side_effect=decode),
        ):
            await cog.ended_scanner()
        self.assertEqual(len(set(threads)), 1)
        self.assertNotEqual(threads[0], loop_thread)
        self.assertEqual([doc["_id"] for doc in cog.ended_uploads.docs], ["a", "b"])

    async def test_malformed_auction_items_are_skipped(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        with self.assertLogs(auctionhouse.logger, level="WARNING"):
            await cog.process_auction(
                {"uuid": "a"}, *auctionhouse.decode_items([{"uuid": "a"}])
            )
        self.assertEqual(cog.active_uploads.docs, [])

    async def test_leather_colors_use_the_low_24_bits(self):
        auction = {
            "uuid": "a",
            "item_name": "Boots",
            "bin": True,
            "starting_bid": 1,
            "auctioneer": "b" * 32,
        }
        item = {
            "tag": {
                "display": {"color": 0x1123456},
                "ExtraAttributes": {"id": "TEST_HELMET"},
            }
        }
        player = Mock(name="Player", avatar="", id="b" * 32)
        with patch.object(auctionhouse.mojang, "get", return_value=player):
            embed = await auctionhouse.make_auction_embed(auction, item)
        self.assertEqual(embed.color.value, 0x123456)
        self.assertTrue(embed.thumbnail.url.endswith("/123456.png"))

    async def test_ended_fire_sales_are_forgotten_and_can_repeat(self):
        cog = firesaletracker.FireSaleTrackerCog(support.make_bot())
        cog.initialized = False
        cog.data.data = {"OLD": {"end": 1_000}, "LIVE": {"end": 10**15}}
        with (
            patch.object(firesaletracker, "get_fire_sales", return_value={}),
            patch.object(firesaletracker, "send", new_callable=AsyncMock),
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
            patch("skypixel.storage.json_store.write_json", new_callable=AsyncMock),
        ):
            await cog.poll()
            self.assertEqual(set(cog.data), {"LIVE"})
            cog.data.data = {}
            with patch.object(
                firesaletracker,
                "get_fire_sales",
                return_value={"OLD": {"end": 10**15}},
            ):
                with patch.object(cog, "make_fire_sale_embed") as make:
                    await cog.poll()
        make.assert_called_once()


class RankChangeAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_rank_change_sends_one_alert_to_both_ranks_channels(self):
        cog = ranktracker.RankTrackerCog(support.make_bot())
        channels = {"youtube": {1: "a", 2: "b"}, "staff": {2: "c", 3: "d"}}
        with (
            patch.object(ranktracker.constants, "RANK_TRACKER_CHANNELS", channels),
            patch.object(
                ranktracker.alerts, "broadcast", new_callable=AsyncMock
            ) as broadcast,
        ):
            await cog.on_rank_change("uuid", "Name", "youtube", "staff")
        broadcast.assert_awaited_once()
        self.assertEqual(broadcast.await_args.args[1], {1: "a", 2: "c", 3: "d"})
        self.assertEqual(
            broadcast.await_args.kwargs["embed"].title,
            "Name went from [YOUTUBE] to [STAFF] rank!",
        )


class WatchlistCommandTests(unittest.IsolatedAsyncioTestCase):
    def cog(self, name):
        cog = ranktracker.RankTrackerCog(support.make_bot(is_owner=AsyncMock()))
        cog.bot.is_owner.return_value = False
        cog.watch_list = JsonWrapper(f"{support.TEST_STORAGE.name}/{name}.json")
        cog.watch_list.data = {"b": {"rankname": None, "name": "Player", "added_by": 1}}
        return cog

    async def unwatch(self, cog, user_id):
        inter = support.make_inter(author=Mock(id=user_id))
        player = Mock(id="b")
        player.name = "Player"
        with patch.object(
            ranktracker.mojang, "get", new_callable=AsyncMock, return_value=player
        ):
            await cog.unwatch.callback(cog, inter, "Player")
        return inter

    async def test_only_the_user_who_added_a_player_can_remove_them(self):
        cog = self.cog("unwatch-other")
        inter = await self.unwatch(cog, 2)
        self.assertEqual(support.error_title(inter), "Not Your Player!")
        self.assertIn("b", cog.watch_list)
        inter = await self.unwatch(cog, 1)
        self.assertNotIn("b", cog.watch_list)
        self.assertEqual(
            inter.send.call_args.kwargs["embed"].title, "Removed From Watchlist"
        )

    async def test_first_scan_keeps_who_added_the_player(self):
        cog = self.cog("watch-scan")
        with patch.object(ranktracker, "get_rankname", return_value="§7Player"):
            await cog.do_watchlist()
        self.assertEqual(
            cog.watch_list["b"],
            {"rankname": "§7Player", "name": "Player", "added_by": 1},
        )


class StatusCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_item_counts_are_reused_between_status_changes(self):
        item_db = Mock(count_documents=AsyncMock(return_value=1234))
        bot = Mock(
            change_presence=AsyncMock(),
            services=Mock(item_db=item_db),
        )
        cog = StatusUpdaterCog(bot)
        await cog._item_count_status("TEST_MEMENTO")
        await cog._item_count_status("TEST_MEMENTO")
        item_db.count_documents.assert_awaited_once()
        self.assertEqual(
            bot.change_presence.await_args.kwargs["activity"].state,
            "Tracking 1,234 Test Memento items",
        )
