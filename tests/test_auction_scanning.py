import unittest
from unittest.mock import AsyncMock, Mock, patch

import tests.support as support
from skypixel.trackers import auctionhouse


class PoiAuthorTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_rank_lookup_falls_back_to_the_username(self):
        error = auctionhouse.RequestException("HTTP Error 429")
        player = Mock()
        player.name = "Player"
        with (
            patch.object(auctionhouse.ranktracker, "get_rankname", side_effect=error),
            patch.object(auctionhouse.mojang, "get", return_value=player),
        ):
            self.assertEqual(await auctionhouse.poi_author_name("a" * 32), "Player")

    async def test_failed_username_lookup_falls_back_to_the_uuid(self):
        error = auctionhouse.RequestException("down")
        with (
            patch.object(auctionhouse.ranktracker, "get_rankname", side_effect=error),
            patch.object(auctionhouse.mojang, "get", side_effect=error),
        ):
            self.assertEqual(await auctionhouse.poi_author_name("a" * 32), "a" * 32)


class AuctionScanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_black_armor_keeps_its_color_thumbnail_and_exotic_alert(self):
        cog = self.cog()
        auction = {
            "uuid": "auction",
            "auctioneer": "a" * 32,
            "item_name": "Black Helmet",
            "starting_bid": 1,
            "bin": True,
        }
        item = {
            "tag": {
                "display": {"color": 0},
                "ExtraAttributes": {"uuid": "item", "id": "TEST_HELMET"},
            }
        }
        with (
            patch.object(
                cog.listener, "on_exotic_auction", new_callable=AsyncMock
            ) as alert,
            patch.object(
                auctionhouse.mojang,
                "get",
                return_value=Mock(name="Player", avatar="", id="a" * 32),
            ),
        ):
            await cog.on_auction(auction, item)
            embed = await auctionhouse.make_auction_embed(auction, item)
        alert.assert_awaited_once_with(auction, item, "spook", "000000")
        self.assertEqual(embed.color.value, 0)
        self.assertTrue(embed.thumbnail.url.endswith("/000000.png"))

    async def test_accessory_reforges_accept_both_category_fields(self):
        for fields in (
            {"category": "accessories"},
            {"categories": ["accessories"]},
            {"category": "accessories", "categories": []},
            {"category": "armor", "categories": ["accessories"]},
        ):
            with self.subTest(fields=fields):
                cog = self.cog()
                auction = {"uuid": "auction", "auctioneer": "a" * 32, **fields}
                item = {
                    "tag": {
                        "ExtraAttributes": {
                            "uuid": "item",
                            "id": "TEST_HELMET",
                            "modifier": "forceful",
                        }
                    }
                }
                with (
                    patch.object(
                        cog.listener, "on_og_reforge_auction", new_callable=AsyncMock
                    ) as og,
                    patch.object(
                        cog.listener,
                        "on_semi_og_reforge_auction",
                        new_callable=AsyncMock,
                    ) as semi,
                ):
                    await cog.on_auction(auction, item)
                og.assert_not_awaited()
                semi.assert_awaited_once_with(auction, item)

    def page(self, number, starts, updated=200_000):
        return {
            "page": number,
            "totalPages": 3,
            "lastUpdated": updated,
            "auctions": [
                {"uuid": f"{number}-{index}", "start": start, "item_bytes": ""}
                for index, start in enumerate(starts)
            ],
        }

    def cog(self):
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        cog.last_scanned_active = 100_000
        return cog

    async def test_next_page_is_read_while_all_starts_exceed_the_cutoff(self):
        cog = self.cog()
        pages = [self.page(0, [150_000, 140_000]), self.page(1, [130_000, 100_000])]
        with (
            patch.object(
                auctionhouse, "get_active_auctions", side_effect=pages
            ) as fetch,
            patch.object(
                auctionhouse,
                "decode_items",
                side_effect=lambda records: [{} for _ in records],
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            await cog.active_scanner()
        self.assertEqual([call.args for call in fetch.await_args_list], [(), (1,)])
        self.assertEqual(process.await_count, 4)
        self.assertEqual(cog.last_scanned_active, 200_000)

    async def test_empty_page_and_last_page_stop_pagination(self):
        for tail in (self.page(1, []), self.page(2, [170_000])):
            cog = self.cog()
            pages = [self.page(0, [180_000]), self.page(1, [175_000]), tail]
            if not tail["auctions"]:
                pages.pop(1)
            with (
                patch.object(
                    auctionhouse, "get_active_auctions", side_effect=pages
                ) as fetch,
                patch.object(
                    auctionhouse,
                    "decode_items",
                    side_effect=lambda records: [{} for _ in records],
                ),
                patch.object(cog, "process_auction", new_callable=AsyncMock),
            ):
                await cog.active_scanner()
            self.assertEqual(fetch.await_count, len(pages))

    async def test_first_page_is_enough_at_or_below_the_cutoff(self):
        for earliest in (99_999, 100_000):
            cog = self.cog()
            with (
                patch.object(
                    auctionhouse,
                    "get_active_auctions",
                    return_value=self.page(0, [190_000, earliest]),
                ) as fetch,
                patch.object(
                    auctionhouse,
                    "decode_items",
                    side_effect=lambda records: [{} for _ in records],
                ),
                patch.object(cog, "process_auction", new_callable=AsyncMock),
            ):
                await cog.active_scanner()
            fetch.assert_awaited_once_with()

    async def test_failed_page_fetch_keeps_the_checkpoint_and_sends_no_alerts(self):
        cog = self.cog()
        page = self.page(0, [190_000])
        with (
            patch.object(
                auctionhouse, "get_active_auctions", side_effect=[page, OSError]
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            with self.assertRaises(OSError):
                await cog.active_scanner()
        process.assert_not_awaited()
        self.assertEqual(cog.last_scanned_active, 100_000)

    async def test_changed_snapshot_keeps_the_checkpoint_and_sends_no_alerts(self):
        cog = self.cog()
        with (
            patch.object(
                auctionhouse,
                "get_active_auctions",
                side_effect=[
                    self.page(0, [190_000]),
                    self.page(1, [170_000], updated=260_000),
                ],
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            with self.assertRaisesRegex(ValueError, "changed snapshots"):
                await cog.active_scanner()
        process.assert_not_awaited()
        self.assertEqual(cog.last_scanned_active, 100_000)

    async def test_failed_decode_keeps_both_scanner_checkpoints_for_retry(self):
        for ended in (False, True):
            cog = self.cog()
            cog.last_scanned_ended = 100_000
            page = self.page(0, [150_000])
            page["totalPages"] = 1
            page["auctions"][0]["timestamp"] = 150_000
            fetch = "get_ended_auctions" if ended else "get_active_auctions"
            scan = cog.ended_scanner if ended else cog.active_scanner
            with (
                patch.object(auctionhouse, fetch, return_value=page),
                patch.object(
                    auctionhouse,
                    "decode_items",
                    side_effect=[RuntimeError("decode failed"), [{}]],
                ),
                patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
            ):
                with self.assertRaises(RuntimeError):
                    await scan()
                self.assertEqual(cog.last_scanned_active, 100_000)
                self.assertEqual(cog.last_scanned_ended, 100_000)
                await scan()
            process.assert_awaited_once()

    async def test_failed_decode_on_the_second_page_sends_no_first_page_alerts(self):
        cog = self.cog()
        with (
            patch.object(
                auctionhouse,
                "get_active_auctions",
                side_effect=[self.page(0, [190_000]), self.page(1, [100_000])],
            ),
            patch.object(
                auctionhouse,
                "decode_items",
                side_effect=[[{}], RuntimeError("decode failed")],
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            with self.assertRaises(RuntimeError):
                await cog.active_scanner()
        process.assert_not_awaited()
        self.assertEqual(cog.last_scanned_active, 100_000)

    async def test_overflow_within_the_next_minute_reads_the_second_page(self):
        cog = self.cog()
        first = self.page(0, [150_000] * 1000, updated=160_000)
        second = self.page(1, [140_000, 99_999], updated=160_000)
        with (
            patch.object(
                auctionhouse, "get_active_auctions", side_effect=[first, second]
            ) as fetch,
            patch.object(
                auctionhouse,
                "decode_items",
                side_effect=lambda records: [{} for _ in records],
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            await cog.active_scanner()
        self.assertEqual([call.args for call in fetch.await_args_list], [(), (1,)])
        self.assertEqual(process.await_count, 1001)
        self.assertEqual(cog.last_scanned_active, 160_000)
