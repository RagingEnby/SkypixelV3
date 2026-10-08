import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http, mojang
from skypixel.domain import colors
from skypixel.domain.nbt import ItemDecodeError, decode_single
from skypixel.storage.mongo import UploadQueue
from skypixel.trackers import ranktracker
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)
ACTIVE_URL: str = "https://api.hypixel.net/v2/skyblock/auctions?page={}"
ENDED_URL: str = "https://api.hypixel.net/v2/skyblock/auctions_ended"


async def finish_tasks(*tasks: Coroutine[Any, Any, Any]) -> list[Any]:
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


def validate_auctions(data: Any) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("lastUpdated"), int)
        or not isinstance(data.get("auctions"), list)
    ):
        raise ValueError(
            "The auction API did not return a timestamp and auctions list."
        )
    return data


def decode_items(auctions: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Decode each auction's item, or return None for a malformed one."""
    items = []
    for auction in auctions:
        try:
            items.append(decode_single(auction["item_bytes"]))
        except (ItemDecodeError, KeyError):  # fmt: skip
            items.append(None)
    return items


async def get_active_auctions(page: int = 0) -> dict[str, Any]:
    return validate_auctions(await http.get_json(ACTIVE_URL.format(page)))


async def get_ended_auctions() -> dict[str, Any]:
    return validate_auctions(await http.get_json(ENDED_URL))


async def make_auction_embed(
    auction: dict[str, Any], item: dict[str, Any]
) -> disnake.Embed:
    tag = item.get("tag", {})
    display = tag.get("display", {})
    embed = disnake.Embed(
        url=constants.AUCTION_URL.format(auction["uuid"]),
        title=auction["item_name"],
        color=(display.get("color") or 0) & 0xFFFFFF
        or constants.RARITY_COLORS.get(auction.get("tier", "COMMON")),
    )
    embed.set_thumbnail(
        utils.get_item_image(
            item_id=tag.get("ExtraAttributes", {}).get("id", "DIRT"),
            color=f"{display['color'] & 0xFFFFFF:06X}"
            if display.get("color")
            else None,
            durability=item.get("Damage"),
        )
    )
    embed.set_footer(text="/viewauction " + auction["uuid"])
    embed.add_field(
        name="Price" if auction["bin"] else "Starting Bid",
        value=utils.numerize(auction["starting_bid"]),
        inline=True,
    )
    if not auction["bin"]:
        embed.add_field(
            name="Auction End", value=f"<t:{auction['end'] // 1000}:R>", inline=True
        )
    auctioneer = await mojang.get(auction["auctioneer"])
    embed.set_author(
        name=auctioneer.name,
        icon_url=auctioneer.avatar,
        url=constants.STATS_URL.format(auctioneer.id),
    )
    return embed


class AHListener:
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    async def on_admin_spawned_auction(
        self, auction: dict[str, Any], item: dict[str, Any]
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Origin Tag",
            value=item["tag"]["ExtraAttributes"]["originTag"],
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.ADMIN_SPAWNED_ITEMS_CHANNEL, embed=embed
        )

    async def on_og_reforge_auction(
        self, auction: dict[str, Any], item: dict[str, Any]
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Reforge",
            value=item["tag"]["ExtraAttributes"]["modifier"],
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.OG_REFORGES_CHANNEL, embed=embed
        )

    async def on_semi_og_reforge_auction(
        self, auction: dict[str, Any], item: dict[str, Any]
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Reforge",
            value=item["tag"]["ExtraAttributes"]["modifier"],
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.SEMI_OG_REFORGES_CHANNEL, embed=embed
        )

    async def on_poi_auction(self, auction: dict[str, Any], item: dict[str, Any]):
        rankname = utils.remove_color_codes(
            await ranktracker.get_rankname(auction["auctioneer"])
        )
        embed = await make_auction_embed(auction, item)
        embed.set_author(
            name=rankname,
            icon_url=constants.MC_HEAD_IMAGE.format(auction["auctioneer"]),
        )
        await utils.notify_to_channel(
            self.bot, constants.POI_AUCTIONS_CHANNEL, embed=embed
        )

    async def on_old_item_auction(
        self, auction: dict[str, Any], item: dict[str, Any], timestamp: int
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Created At",
            value=f"<t:{timestamp}>\n-# <t:{timestamp}:R>",
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.OLD_ITEM_AUCTIONS_CHANNEL, embed=embed
        )

    async def on_seymour_auction(
        self, auction: dict[str, Any], item: dict[str, Any], hex_code: str
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(name="Hex Code", value=f"#{hex_code}", inline=True)
        armor_type = constants.SEYMOUR_IDS[item["tag"]["ExtraAttributes"]["id"]]
        top_5 = colors.get_top_5(armor_type, hex_code)
        embed.description = (
            "```\n"
            + "\n".join([f"{k}: {round(v, 2)}" for k, v in top_5.items()])
            + "```"
        )
        await utils.notify_to_channel(
            self.bot, constants.SEYMOUR_AUCTIONS_CHANNEL, embed=embed
        )

    async def on_exotic_auction(
        self,
        auction: dict[str, Any],
        item: dict[str, Any],
        exotic_type: colors.ExoticType,
        hex_code: str,
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(name="Hex Code", value=f"#{hex_code}")
        embed.add_field(
            name="Exotic Type", value=exotic_type.replace("_", " ").title(), inline=True
        )
        send_tasks = [
            utils.notify_to_channel(
                self.bot, constants.EXOTIC_AUCTIONS_CHANNEL, embed=embed
            )
        ]
        thread_id = constants.EXOTIC_AUCTIONS_THREADS.get(exotic_type)
        if thread_id:
            send_tasks.append(
                utils.notify_to_channel(
                    self.bot,
                    constants.EXOTIC_AUCTIONS_THREADS_PARENT,
                    thread_id=thread_id,
                    embed=embed,
                )
            )
        await finish_tasks(*send_tasks)

    async def on_cake_soul_auction(self, auction: dict[str, Any], item: dict[str, Any]):
        embed = await make_auction_embed(auction, item)
        dye_data = constants.MINECRAFT_DYES.get(item.get("Damage"))
        if dye_data:
            embed.title = dye_data["colorName"].title() + " Cake Soul"
            embed.color = dye_data["hex"]
        cake_owner = (
            item.get("tag", {}).get("ExtraAttributes", {}).get("cake_owner") or "None"
        )
        embed.add_field(
            name="Cake Owner", value=utils.remove_color_codes(cake_owner), inline=True
        )
        pings = []
        if (
            auction["bin"]
            and auction["starting_bid"] <= 7_500_000
            and dye_data
            and dye_data["colorName"] == "red"
        ):
            pings.append(f"<@&{constants.CHEAP_RED_SOUL_ROLE}>")
        if auction["bin"] and auction["starting_bid"] <= 5_000_000:
            pings.append(f"<@&{constants.CHEAP_SOUL_ROLE}>")
        await utils.notify_to_channel(
            self.bot, constants.CAKE_SOUL_AUCTIONS_CHANNEL, " ".join(pings), embed=embed
        )

    async def on_editioned_auction(
        self,
        auction: dict[str, Any],
        item: dict[str, Any],
        edition: int,
        timestamp: int | None,
    ):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Edition", value=f"#{utils.commaize(edition)}", inline=True
        )
        recipient_name = (
            item.get("tag", {}).get("ExtraAttributes", {}).get("recipient_name")
        )
        if recipient_name:
            embed.add_field(
                name="Recipient Name",
                value=utils.esc_mrkdwn(utils.remove_color_codes(recipient_name)),
                inline=True,
            )
        if timestamp:
            embed.add_field(
                name="Created At",
                value=f"<t:{timestamp}>\n-# <t:{timestamp}:R>",
                inline=True,
            )
        await utils.notify_to_channel(
            self.bot, constants.EDITIONED_AUCTIONS_CHANNEL, embed=embed
        )


class AuctionTrackerCog(PollingCog):
    interval = 15

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.active_uploads = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "auctions"
        )
        self.ended_uploads = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "ended_auctions"
        )
        self.last_scanned_active = 0
        self.last_scanned_ended = 0
        self._scan_semaphore = asyncio.Semaphore(20)
        self._late_polls = {"active": 0, "ended": 0}
        self.listener = AHListener(bot)

    def next_delay(self, scanner: str, last_updated: int, changed: bool) -> float:
        """Wait for the next API update, backing off while the API is late."""
        if changed:
            self._late_polls[scanner] = 0
        time_until_update = last_updated / 1000 + 60 - time.time()
        if time_until_update > 0:
            return time_until_update
        late_polls = self._late_polls[scanner]
        self._late_polls[scanner] = late_polls + 1
        return float(min(2**late_polls, 16))

    async def upload_queue(self):
        await finish_tasks(self.active_uploads.flush(), self.ended_uploads.flush())

    def log_auction(self, auction: dict[str, Any], item: dict[str, Any], ended: bool):
        doc = auction.copy()
        doc["item_data"] = item
        if ended:
            doc["_id"] = doc.pop("auction_id")
            self.ended_uploads.append(doc)
        else:
            doc["_id"] = doc.pop("uuid")
            self.active_uploads.append(doc)

    async def on_auction(
        self, auction: dict[str, Any], item: dict[str, Any], new: bool = True
    ):
        self.log_auction(auction, item, ended=False)
        if not new:
            return
        extra_attributes = item.get("tag", {}).get("ExtraAttributes", {})
        if not extra_attributes.get("uuid"):
            return
        item_id = extra_attributes.get("id")
        timestamp = (
            utils.normalize_timestamp(extra_attributes["timestamp"])
            if extra_attributes.get("timestamp")
            else None
        )
        color = item.get("tag", {}).get("display", {}).get("color")
        hex_code = f"{color & 0xFFFFFF:06X}" if color else None
        exotic_type = (
            colors.get_exotic_type(item_id, hex_code)
            if item_id and hex_code and not extra_attributes.get("dye_item")
            else None
        )
        edition = extra_attributes.get(
            "edition", extra_attributes.get("basket_edition")
        )
        accessory = auction.get(
            "category"
        ) == "accessories" or "accessories" in auction.get("categories", [])
        tasks: list[Coroutine] = []

        if extra_attributes.get("originTag") in constants.ADMIN_ORIGIN_TAGS:
            tasks.append(self.listener.on_admin_spawned_auction(auction, item))
        if not accessory and extra_attributes.get("modifier") in constants.OG_REFORGES:
            tasks.append(self.listener.on_og_reforge_auction(auction, item))
        if accessory and extra_attributes.get("modifier", "none") != "none":
            tasks.append(self.listener.on_semi_og_reforge_auction(auction, item))
        if auction["auctioneer"] in ranktracker.POI_UUIDS:
            tasks.append(self.listener.on_poi_auction(auction, item))
        if (
            timestamp
            and timestamp <= 1575910800
            and auction["starting_bid"] <= 100_000_000
        ):
            tasks.append(self.listener.on_old_item_auction(auction, item, timestamp))
        if item_id in constants.SEYMOUR_IDS and hex_code:
            tasks.append(self.listener.on_seymour_auction(auction, item, hex_code))
        if exotic_type and hex_code:
            tasks.append(
                self.listener.on_exotic_auction(auction, item, exotic_type, hex_code)
            )
        if item_id == "CAKE_SOUL":
            tasks.append(self.listener.on_cake_soul_auction(auction, item))
        if edition and edition > 0:
            tasks.append(
                self.listener.on_editioned_auction(auction, item, edition, timestamp)
            )
        if tasks:
            await finish_tasks(*tasks)

    async def on_auction_end(self, auction: dict[str, Any], item: dict[str, Any]):
        self.log_auction(auction, item, ended=True)

    async def process_auction(
        self,
        auction: dict[str, Any],
        item: dict[str, Any] | None,
        *,
        ended: bool = False,
        new: bool = True,
    ):
        if item is None:
            logger.warning(
                "Skipped malformed item data in auction %s.",
                auction.get("auction_id" if ended else "uuid"),
            )
            return
        async with self._scan_semaphore:
            try:
                if ended:
                    await self.on_auction_end(auction, item)
                else:
                    await self.on_auction(auction, item, new=new)
            except Exception:
                logger.exception("Cannot process auction record.")

    async def active_scanner(self) -> float:
        page_0 = await get_active_auctions()
        if not self.last_scanned_active:
            self.last_scanned_active = page_0["lastUpdated"]
        changed = page_0["lastUpdated"] != self.last_scanned_active
        if changed:
            pages = [page_0]
            page = page_0
            while (
                page["auctions"]
                and len(pages) < page_0.get("totalPages", 1)
                and min(a.get("start", 0) for a in page["auctions"])
                > self.last_scanned_active + 60_000
            ):
                page = await get_active_auctions(len(pages))
                if page["lastUpdated"] != page_0["lastUpdated"]:
                    raise ValueError("The auction API changed snapshots between pages.")
                pages.append(page)
            decoded_pages = []
            for page in pages:
                auctions = [
                    a
                    for a in page["auctions"]
                    if a.get("last_updated", a.get("start", 0))
                    >= self.last_scanned_active
                ]
                logger.debug("got %s auctions", len(auctions))
                # One thread call per page. The NBT parser holds the GIL, so
                # more threads would not decode faster.
                items = await asyncio.to_thread(decode_items, auctions)
                decoded_pages.append((auctions, items))
            for auctions, items in decoded_pages:
                await finish_tasks(
                    *[
                        self.process_auction(
                            a,
                            item,
                            new=a.get("start", 0) >= self.last_scanned_active,
                        )
                        for a, item in zip(auctions, items, strict=True)
                    ]
                )
            self.last_scanned_active = page_0["lastUpdated"]
            logger.debug("processed auctions")
        return self.next_delay("active", self.last_scanned_active, changed)

    async def ended_scanner(self) -> float:
        data = await get_ended_auctions()
        if not self.last_scanned_ended:
            self.last_scanned_ended = data["lastUpdated"]
        changed = data["lastUpdated"] != self.last_scanned_ended
        if changed:
            auctions = [
                a
                for a in data["auctions"]
                if a.get("timestamp", 0) >= self.last_scanned_ended
            ]
            logger.debug("got %s ended auctions", len(auctions))
            items = await asyncio.to_thread(decode_items, auctions)
            await finish_tasks(
                *(
                    self.process_auction(a, item, ended=True)
                    for a, item in zip(auctions, items, strict=True)
                )
            )
            self.last_scanned_ended = data["lastUpdated"]
            logger.debug("processed ended auctions")
        return self.next_delay("ended", self.last_scanned_ended, changed)

    async def poll(self):
        delays = await asyncio.gather(
            self.active_scanner(), self.ended_scanner(), return_exceptions=True
        )
        try:
            await self.upload_queue()
        except Exception:
            # The queues keep failed batches, so the next poll retries them.
            # Scanning should keep its own schedule while MongoDB is down.
            logger.exception("Cannot upload auction records.")
        for delay in delays:
            if isinstance(delay, BaseException):
                raise delay
        return min(delays)

    async def close_resources(self):
        await finish_tasks(self.active_uploads.close(), self.ended_uploads.close())
