import unittest
from unittest.mock import AsyncMock, patch

import tests.support as support
from skypixel.trackers import firesaletracker, ranktracker


class RankValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_different_partial_lists_reset_confirmation_and_keep_channel_counts(
        self,
    ):
        cog = ranktracker.RankTrackerCog(support.make_bot())
        before = {str(i): {"name": f"P{i}", "rank": "youtube"} for i in range(6)}
        cog.data.data = before
        snapshots = [{str(i): before[str(i)]} for i in range(3)]
        with (
            patch.object(cog, "do_watchlist", new_callable=AsyncMock),
            patch.object(
                ranktracker,
                "get_player_ranks",
                side_effect=snapshots + [snapshots[-1]] * 2,
            ),
            patch.object(ranktracker, "invalidate_rank_lists"),
            patch.object(
                ranktracker, "edit_stat_channels", new_callable=AsyncMock
            ) as counts,
            patch.object(cog, "on_rank_remove", new_callable=AsyncMock) as remove,
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
            self.assertLogs(ranktracker.logger, level="ERROR"),
        ):
            for _ in snapshots:
                await cog.poll()
                self.assertEqual(cog.shrunken_polls, 1)
            self.assertEqual(cog.data.to_dict(), before)
            remove.assert_not_awaited()
            counts.assert_not_awaited()
            await cog.poll()
            counts.assert_not_awaited()
            await cog.poll()
        self.assertEqual(remove.await_count, 5)
        self.assertEqual(cog.data.to_dict(), snapshots[-1])
        counts.assert_awaited_once_with(
            cog.bot, {"youtube": [{"id": "2", "name": "P2"}]}
        )
        self.assertEqual(cog.shrunken_polls, 0)
        self.assertIsNone(cog.shrunken_changes)

    async def test_healthy_response_resets_pending_rank_removals(self):
        cog = ranktracker.RankTrackerCog(support.make_bot())
        before = {str(i): {"name": f"P{i}", "rank": "youtube"} for i in range(6)}
        after = {"0": before["0"]}
        cog.data.data = before
        with (
            patch.object(cog, "do_watchlist", new_callable=AsyncMock),
            patch.object(
                ranktracker, "get_player_ranks", side_effect=[after, before, after]
            ),
            patch.object(ranktracker, "invalidate_rank_lists"),
            patch.object(ranktracker, "edit_stat_channels", new_callable=AsyncMock),
            patch.object(cog, "on_rank_remove", new_callable=AsyncMock) as remove,
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock),
            self.assertLogs(ranktracker.logger, level="ERROR"),
        ):
            await cog.poll()
            await cog.poll()
            self.assertEqual(cog.shrunken_polls, 0)
            self.assertIsNone(cog.shrunken_changes)
            await cog.poll()
        remove.assert_not_awaited()
        self.assertEqual(cog.shrunken_polls, 1)
        self.assertEqual(cog.data.to_dict(), before)


class FireSaleInitializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_first_poll_is_saved_and_a_later_sale_is_announced(self):
        cog = firesaletracker.FireSaleTrackerCog(support.make_bot())
        cog.initialized = False
        cog.data.data = {}
        sale = {"amount": 1, "price": 1, "start": 1000, "end": 2000}
        with (
            patch.object(
                firesaletracker, "get_fire_sales", side_effect=[{}, {"NEW": sale}]
            ),
            patch.object(firesaletracker, "send", new_callable=AsyncMock) as notify,
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
            patch("skypixel.storage.json.write_json", new_callable=AsyncMock) as save,
        ):
            await cog.poll()
            self.assertTrue(cog.initialized)
            save.assert_awaited_once_with(cog.data.file_path, {}, 2)
            notify.assert_not_awaited()
            await cog.poll()
        notify.assert_awaited_once()
        self.assertIn("NEW", cog.data)

    async def test_failed_empty_first_save_keeps_initialization_pending(self):
        cog = firesaletracker.FireSaleTrackerCog(support.make_bot())
        cog.initialized = False
        cog.data.data = {}
        with (
            patch.object(firesaletracker, "get_fire_sales", return_value={}),
            patch.object(cog.uploads, "flush", new_callable=AsyncMock),
            patch("skypixel.storage.json.write_json", side_effect=[OSError, None]),
        ):
            with self.assertRaises(OSError):
                await cog.poll()
            self.assertFalse(cog.initialized)
            await cog.poll()
        self.assertTrue(cog.initialized)
