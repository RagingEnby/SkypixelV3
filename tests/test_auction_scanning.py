import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import tests.support as support
from skypixel.domain.types import Document
from skypixel.trackers import auctionhouse


def decode_empty(records: list[Document]) -> list[Document]:
    """Stand in for decode_items with one empty item per auction."""
    return [{} for _ in records]


class AuctionScanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_black_armor_keeps_its_color_thumbnail_and_exotic_alert(self) -> None:
        cog = self.cog()
        auction: auctionhouse.Auction = {
            "uuid": "auction",
            "auctioneer": "a" * 32,
            "item_name": "Black Helmet",
            "starting_bid": 1,
            "bin": True,
        }
        item: auctionhouse.Item = {
            "tag": {
                "display": {"color": 0},
                "ExtraAttributes": {"uuid": "item", "id": "TEST_HELMET"},
            }
        }
        with (
            patch.object(auctionhouse, "send_alert", new_callable=AsyncMock) as alert,
            patch.object(
                auctionhouse.mojang,
                "get",
                return_value=Mock(name="Player", avatar="", id="a" * 32),
            ),
        ):
            await cog.on_auction(auction, item)
            embed = await auctionhouse.make_auction_embed(auction, item)
        alert.assert_awaited_once()
        assert alert.await_args is not None
        _bot, rule, info = alert.await_args.args
        self.assertEqual(rule.name, "exotic")
        self.assertIs(info.auction, auction)
        self.assertIs(info.item, item)
        self.assertEqual((info.exotic_type, info.hex_code), ("spook", "000000"))
        assert embed.color is not None
        assert embed.thumbnail.url is not None
        self.assertEqual(embed.color.value, 0)
        self.assertTrue(embed.thumbnail.url.endswith("/000000.png"))

    async def test_accessory_reforges_accept_both_category_fields(self) -> None:
        field_sets: tuple[Document, ...] = (
            {"category": "accessories"},
            {"categories": ["accessories"]},
            {"category": "accessories", "categories": []},
            {"category": "armor", "categories": ["accessories"]},
        )
        for fields in field_sets:
            with self.subTest(fields=fields):
                cog = self.cog()
                auction: auctionhouse.Auction = {
                    "uuid": "auction",
                    "auctioneer": "a" * 32,
                    **fields,
                }
                item: auctionhouse.Item = {
                    "tag": {
                        "ExtraAttributes": {
                            "uuid": "item",
                            "id": "TEST_HELMET",
                            "modifier": "forceful",
                        }
                    }
                }
                with patch.object(
                    auctionhouse, "send_alert", new_callable=AsyncMock
                ) as alert:
                    await cog.on_auction(auction, item)
                fired = [call.args[1].name for call in alert.await_args_list]
                self.assertNotIn("og_reforge", fired)
                self.assertEqual(fired.count("semi_og_reforge"), 1)
                info = alert.await_args_list[fired.index("semi_og_reforge")].args[2]
                self.assertIs(info.auction, auction)
                self.assertIs(info.item, item)

    def page(self, number: int, starts: list[int], updated: int = 200_000) -> Document:
        return {
            "page": number,
            "totalPages": 3,
            "lastUpdated": updated,
            "auctions": [
                {"uuid": f"{number}-{index}", "start": start, "item_bytes": ""}
                for index, start in enumerate(starts)
            ],
        }

    def cog(self) -> auctionhouse.AuctionTrackerCog:
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        cog.last_scanned_active = 100_000
        return cog

    async def test_next_page_is_read_while_all_starts_exceed_the_cutoff(self) -> None:
        cog = self.cog()
        pages = [self.page(0, [150_000, 140_000]), self.page(1, [130_000, 100_000])]
        with (
            patch.object(
                auctionhouse, "get_active_auctions", side_effect=pages
            ) as fetch,
            patch.object(
                auctionhouse,
                "decode_items",
                side_effect=decode_empty,
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            await cog.active_scanner()
        self.assertEqual([call.args for call in fetch.await_args_list], [(), (1,)])
        self.assertEqual(process.await_count, 4)
        self.assertEqual(cog.last_scanned_active, 200_000)

    async def test_empty_page_and_last_page_stop_pagination(self) -> None:
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
                    side_effect=decode_empty,
                ),
                patch.object(cog, "process_auction", new_callable=AsyncMock),
            ):
                await cog.active_scanner()
            self.assertEqual(fetch.await_count, len(pages))

    async def test_first_page_is_enough_at_or_below_the_cutoff(self) -> None:
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
                    side_effect=decode_empty,
                ),
                patch.object(cog, "process_auction", new_callable=AsyncMock),
            ):
                await cog.active_scanner()
            fetch.assert_awaited_once_with()

    async def test_failed_page_fetch_keeps_the_checkpoint_and_sends_no_alerts(
        self,
    ) -> None:
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

    async def test_changed_snapshot_keeps_the_checkpoint_and_sends_no_alerts(
        self,
    ) -> None:
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

    async def test_failed_decode_keeps_both_scanner_checkpoints_for_retry(self) -> None:
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

    async def test_failed_decode_on_the_second_page_sends_no_first_page_alerts(
        self,
    ) -> None:
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

    async def test_overflow_within_the_next_minute_reads_the_second_page(self) -> None:
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
                side_effect=decode_empty,
            ),
            patch.object(cog, "process_auction", new_callable=AsyncMock) as process,
        ):
            await cog.active_scanner()
        self.assertEqual([call.args for call in fetch.await_args_list], [(), (1,)])
        self.assertEqual(process.await_count, 1001)
        self.assertEqual(cog.last_scanned_active, 160_000)

    async def test_alert_embed_shows_the_uuid_when_the_name_lookup_fails(self) -> None:
        auction: auctionhouse.Auction = {
            "uuid": "auction",
            "auctioneer": "a" * 32,
            "item_name": "Item",
            "starting_bid": 1,
            "bin": True,
        }
        with (
            patch.object(auctionhouse.mojang, "get", side_effect=KeyError("a" * 32)),
            self.assertLogs(auctionhouse.logger, level="WARNING"),
        ):
            embed = await auctionhouse.make_auction_embed(auction, {})
        self.assertEqual(embed.author.name, "a" * 32)

    async def test_recent_scan_cursors_survive_a_restart(self) -> None:
        recent = int(time.time() * 1000) - 60_000
        old = int(time.time() * 1000) - 3_600_000
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        cog.last_scanned_active, cog.last_scanned_ended = recent, old
        await cog.save_cursors()
        restarted = auctionhouse.AuctionTrackerCog(support.make_bot())
        self.assertEqual(restarted.last_scanned_active, recent)
        # A cursor from before a long outage would alert on every auction.
        self.assertEqual(restarted.last_scanned_ended, 0)
        await cog.cursors.replace({})

    async def test_stored_auctions_keep_the_decoded_item_only(self) -> None:
        cog = auctionhouse.AuctionTrackerCog(support.make_bot())
        cog.log_auction({"uuid": "a", "item_bytes": "raw"}, {"id": 1}, ended=False)
        cog.log_auction({"auction_id": "b", "item_bytes": "raw"}, {"id": 2}, ended=True)
        self.assertEqual(
            cog.active_uploads.docs, [{"_id": "a", "item_data": {"id": 1}}]
        )
        self.assertEqual(cog.ended_uploads.docs, [{"_id": "b", "item_data": {"id": 2}}])
