import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import tests.support as support
from skypixel import app
from skypixel.storage.json import JsonWrapper
from skypixel.storage.mongo import flush_queue
from skypixel.trackers import (
    auctionhouse,
    firesaletracker,
    jobtracker,
    ranktracker,
    wikitracker,
)
from skypixel.trackers.base import PollingCog
from skypixel.trackers.status import StatusUpdaterCog


class ProbeCog(PollingCog):
    async def poll(self):
        await asyncio.Future()


class PollingTests(unittest.IsolatedAsyncioTestCase):
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
        with (
            patch.object(ranktracker, "WATCH_LIST", state),
            patch.object(ranktracker, "RANK_LIST_CACHE", {"staff": []}),
            patch.object(
                ranktracker, "get_rankname", new_callable=AsyncMock, return_value="same"
            ),
        ):
            await ranktracker.RankTrackerCog.do_watchlist()
            self.assertEqual(ranktracker.RANK_LIST_CACHE, {"staff": []})

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
        state.remove_and_save = AsyncMock(wraps=state.remove_and_save)
        with (
            patch.object(ranktracker, "WATCH_LIST", state),
            patch.object(
                ranktracker, "get_rankname", new_callable=AsyncMock, return_value="new"
            ),
        ):
            await ranktracker.RankTrackerCog.do_watchlist()
        self.assertEqual(state.to_dict(), {})
        self.assertEqual(state.remove_and_save.await_count, 2)


class TrackerStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_fire_sale_save_keeps_the_sale_for_retry(self):
        cog = firesaletracker.FireSaleTrackerCog(Mock())
        cog.data.data = {"OLD": {"amount": 1}}
        with (
            patch.object(firesaletracker, "get_fire_sales", return_value={"NEW": {}}),
            patch.object(cog, "make_fire_sale_embed", return_value=Mock()),
            patch.object(firesaletracker, "send", new_callable=AsyncMock),
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
            patch("skypixel.storage.json.write_json", side_effect=[OSError, None]),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            self.assertNotIn("NEW", cog.data)
            await cog.poll()
        self.assertIn("NEW", cog.data)

    async def test_wiki_upload_failure_does_not_repeat_saved_notifications(self):
        cog = wikitracker.WikiTrackerCog(Mock())
        cog.data.data = {"edits": [1]}
        edit = {"type": "edit", "revid": 2}
        with (
            patch.object(wikitracker, "get_edits", return_value=[edit]),
            patch.object(cog, "on_wiki_edit", new_callable=AsyncMock) as notify,
            patch.object(cog.uploads, "flush", side_effect=[OSError, None]),
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            await cog.poll()
        notify.assert_awaited_once_with(edit)
        self.assertEqual(cog.data["edits"], [1, 2])

    async def test_wiki_editor_cache_expires_and_evicts_old_entries(self):
        now = 0.0
        with (
            patch.object(wikitracker, "EDITOR_CACHE", {}),
            patch.object(wikitracker, "EDITOR_CACHE_LIMIT", 2),
            patch.object(wikitracker.time, "monotonic", side_effect=lambda: now),
            patch.object(
                wikitracker.http, "get_json", return_value={"displayName": "Editor"}
            ) as fetch,
        ):
            await wikitracker.get_editor("First")
            await wikitracker.get_editor("First")
            self.assertEqual(fetch.await_count, 1)
            now = wikitracker.EDITOR_CACHE_TTL
            await wikitracker.get_editor("First")
            self.assertEqual(fetch.await_count, 2)
            await wikitracker.get_editor("Second")
            await wikitracker.get_editor("Third")
            self.assertEqual(set(wikitracker.EDITOR_CACHE), {"Second", "Third"})

    async def test_wiki_history_is_bounded_without_repeating_recent_edits(self):
        cog = wikitracker.WikiTrackerCog(Mock())
        cog.history_limit = 3
        cog.data.data = {"edits": [1, 2, 3]}
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
        edits = [{"type": "edit", "revid": 4}, {"type": "edit", "revid": 3}]
        with (
            patch.object(wikitracker, "get_edits", return_value=edits),
            patch.object(cog, "on_wiki_edit", new_callable=AsyncMock) as notify,
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
        ):
            await cog.poll()
            await cog.poll()
        notify.assert_awaited_once_with(edits[0])
        self.assertEqual(cog.data["edits"], [2, 3, 4])

    async def test_rank_change_retries_only_the_failed_notifications(self):
        cog = ranktracker.RankTrackerCog(Mock())
        before = {"player": {"name": "Before", "rank": "youtube"}}
        after = {"player": {"name": "After", "rank": "staff"}}
        cog.data.data = before
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
        with (
            patch.object(ranktracker.RankTrackerCog, "do_watchlist", AsyncMock()),
            patch.object(ranktracker, "get_player_ranks", return_value=after),
            patch.object(cog, "on_rank_add", new_callable=AsyncMock) as add,
            patch.object(
                cog, "on_rank_remove", side_effect=[OSError("send failed"), None]
            ) as remove,
            patch.object(cog, "on_name_change", new_callable=AsyncMock) as rename,
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            self.assertEqual(cog.data.to_dict(), before)
            await cog.poll()
        add.assert_awaited_once_with("player", "After", "staff")
        self.assertEqual(remove.await_count, 2)
        rename.assert_awaited_once_with("player", "Before", "After", "staff")
        self.assertEqual(cog.data.to_dict(), after)
        self.assertEqual(cog.known_changes, set())

    async def test_fire_sale_notification_failure_keeps_the_sale_for_retry(self):
        cog = firesaletracker.FireSaleTrackerCog(Mock())
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

    async def test_first_wiki_poll_seeds_all_edits_without_notifications(self):
        cog = wikitracker.WikiTrackerCog(Mock())
        cog.data.data = {"edits": []}
        cog.data.replace = AsyncMock(wraps=cog.data.replace)
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

    async def test_failed_alert_does_not_repeat_the_scanned_auctions(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        cog.last_scanned_active = 1000
        auctions = [{"uuid": "a", "start": 1500}, {"uuid": "b", "start": 1500}]
        pages = [
            {"lastUpdated": 2000, "auctions": auctions},
            {"lastUpdated": 3000, "auctions": auctions},
        ]
        with (
            patch.object(auctionhouse, "get_active_auctions", side_effect=pages),
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

    async def test_failed_editor_lookup_still_posts_the_edit(self):
        cog = wikitracker.WikiTrackerCog(Mock())
        edit = {
            "type": "edit",
            "revid": 5,
            "user": "Editor",
            "title": "Page",
            "comment": "fixed `code`",
        }
        with (
            patch.object(wikitracker, "get_editor", side_effect=RuntimeError),
            patch.object(wikitracker, "send", new_callable=AsyncMock) as send,
            self.assertLogs(wikitracker.logger, level="ERROR"),
        ):
            await cog.on_wiki_edit(edit)
        embed = send.await_args.args[0]
        self.assertEqual(embed.author.name, "Editor")
        self.assertEqual(embed.description.count("```"), 2)

    async def test_upload_failure_keeps_the_scanner_schedule(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        with (
            patch.object(cog, "active_scanner", return_value=40.0),
            patch.object(cog, "ended_scanner", return_value=30.0),
            patch.object(cog, "upload_queue", side_effect=OSError),
            self.assertLogs(auctionhouse.logger, level="ERROR"),
        ):
            self.assertEqual(await cog.poll(), 30.0)

    async def test_late_auction_api_backs_off_until_it_updates(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        with patch.object(auctionhouse.time, "time", return_value=1000.0):
            self.assertEqual(cog.next_delay("active", 950_000, False), 10.0)
            delays = [cog.next_delay("active", 900_000, False) for _ in range(6)]
            self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0, 16.0])
            self.assertEqual(cog.next_delay("ended", 900_000, False), 1.0)
            self.assertEqual(cog.next_delay("active", 900_000, True), 1.0)

    async def test_rank_list_that_shrinks_by_half_needs_confirmation(self):
        cog = ranktracker.RankTrackerCog(Mock())
        before = {str(i): {"name": f"P{i}", "rank": "youtube"} for i in range(6)}
        after = {"0": {"name": "P0", "rank": "youtube"}}
        cog.data.data = before
        with (
            patch.object(ranktracker.RankTrackerCog, "do_watchlist", AsyncMock()),
            patch.object(ranktracker, "get_player_ranks", return_value=after),
            patch.object(ranktracker, "invalidate_rank_lists") as invalidate,
            patch.object(cog, "on_rank_remove", new_callable=AsyncMock) as remove,
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
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
        cog = jobtracker.JobTrackerCog(Mock())
        cog.data.data = {"Dev": self.job("Dev").to_dict()}
        with (
            patch.object(jobtracker, "get_jobs", return_value=[]),
            patch.object(cog, "on_job_update", new_callable=AsyncMock) as notify,
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
            self.assertLogs(jobtracker.logger, level="WARNING"),
        ):
            await cog.poll()
            await cog.poll()
            notify.assert_not_awaited()
            await cog.poll()
        notify.assert_awaited_once()
        self.assertEqual(cog.data.to_dict(), {})

    async def test_first_run_saves_jobs_without_notifications(self):
        cog = jobtracker.JobTrackerCog(Mock())
        cog.data.data = {}
        cog.initialized = False
        with (
            patch.object(jobtracker, "get_jobs", return_value=[self.job("Dev")]),
            patch.object(cog, "on_job_update", new_callable=AsyncMock) as notify,
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
        ):
            await cog.poll()
        notify.assert_not_awaited()
        self.assertIn("Dev", cog.data)
        self.assertTrue(cog.initialized)

    async def test_new_job_after_an_empty_saved_list_is_announced(self):
        cog = jobtracker.JobTrackerCog(Mock())
        cog.data.data = {}
        cog.initialized = True
        with (
            patch.object(jobtracker, "get_jobs", return_value=[self.job("Dev")]),
            patch.object(cog, "on_job_update", new_callable=AsyncMock) as notify,
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
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
        cog = ranktracker.RankTrackerCog(Mock())
        inter = Mock(send=AsyncMock())
        with (
            patch.object(ranktracker, "WATCH_LIST", state),
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
        self.assertEqual(inter.send.call_args.kwargs["embed"].title, "Watchlist Full!")

    async def test_auction_items_decode_off_the_event_loop(self):
        cog = auctionhouse.AuctionTrackerCog(Mock())
        loop_thread = threading.get_ident()
        threads = []

        def decode(item_bytes):
            threads.append(threading.get_ident())
            return {}

        with patch.object(auctionhouse, "decode_single", side_effect=decode):
            await cog.on_auction_end({"auction_id": "a", "item_bytes": ""})
        self.assertNotEqual(threads, [loop_thread])
        self.assertEqual(cog.ended_uploads.docs[0]["_id"], "a")
