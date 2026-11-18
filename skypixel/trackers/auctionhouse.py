import asyncio
import logging
import time
from collections.abc import Awaitable, Mapping
from typing import TYPE_CHECKING, NotRequired, TypedDict

import disnake

from skypixel import constants, utils
from skypixel.clients import http, mojang
from skypixel.domain import colors
from skypixel.domain.nbt import ItemDecodeError, NBTData, decode_single
from skypixel.domain.types import JSON, Document
from skypixel.storage.json_store import JsonWrapper
from skypixel.storage.mongo import UploadQueue
from skypixel.storage.notifications import NotificationStorageError
from skypixel.trackers import ranktracker
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger: logging.Logger = logging.getLogger(__name__)
ACTIVE_URL: str = "https://api.hypixel.net/v2/skyblock/auctions?page={}"
ENDED_URL: str = "https://api.hypixel.net/v2/skyblock/auctions_ended"

# One auction record as the auction API returns it.
type Auction = dict[str, JSON]
# The decoded NBT of an auction's item.
type Item = dict[str, NBTData]


class AuctionPage(TypedDict):
    """The parts of an auction API response that the scanners read."""

    lastUpdated: int
    auctions: list[Auction]
    totalPages: NotRequired[int]


async def finish_tasks[T](*tasks: Awaitable[T]) -> list[T]:
    results = await asyncio.gather(*tasks, return_exceptions=True)
    values: list[T] = []
    for result in results:
        if isinstance(result, BaseException):
            raise result
        values.append(result)
    return values


def validate_auctions(data: JSON) -> AuctionPage:
    if (
        not isinstance(data, dict)
        or not isinstance(last_updated := data.get("lastUpdated"), int)
        or not isinstance(auctions := data.get("auctions"), list)
    ):
        raise ValueError(
            "The auction API did not return a timestamp and auctions list."
        )
    if not all(isinstance(auction, dict) for auction in auctions):
        raise ValueError("Each auction must be a JSON object.")
    page: AuctionPage = {
        "lastUpdated": last_updated,
        "auctions": [auction for auction in auctions if isinstance(auction, dict)],
    }
    if "totalPages" in data:
        total_pages = data["totalPages"]
        if not isinstance(total_pages, int):
            raise ValueError("The auction API page count is not a number.")
        page["totalPages"] = total_pages
    return page


def as_number(value: JSON, key: str) -> int | float:
    if not isinstance(value, int | float):
        raise ValueError(f"The auction {key} is not a number.")
    return value


def auction_number(auction: Mapping[str, JSON], key: str) -> int | float:
    return as_number(auction[key], key)


def auction_text(auction: Mapping[str, JSON], key: str) -> str:
    value = auction[key]
    if not isinstance(value, str):
        raise ValueError(f"The auction {key} is not text.")
    return value


def compound(data: Mapping[str, NBTData], key: str) -> Item:
    """Return the NBT compound at key. A missing key raises KeyError."""
    value = data[key]
    if not isinstance(value, dict):
        raise ValueError(f"The item {key} is not a compound tag.")
    return value


def optional_compound(data: Mapping[str, NBTData], key: str) -> Item:
    """Return the NBT compound at key, or an empty one when the key is missing."""
    return compound(data, key) if key in data else {}


def extra_attributes(item: Item) -> Item:
    return optional_compound(optional_compound(item, "tag"), "ExtraAttributes")


def item_color(item: Item) -> int | None:
    color = optional_compound(optional_compound(item, "tag"), "display").get("color")
    if color is not None and not isinstance(color, int):
        raise ValueError("The item color is not a number.")
    return color


def item_text(data: Mapping[str, NBTData], key: str) -> str | None:
    """Return a text tag, or None when the tag is missing or empty."""
    value = data.get(key)
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError(f"The item {key} is not text.")
    return value


def item_timestamp(attributes: Mapping[str, NBTData]) -> int | None:
    value = attributes.get("timestamp")
    if not value:
        return None
    if not isinstance(value, str | int):
        raise ValueError("The item timestamp is not text or a number.")
    return utils.normalize_timestamp(value)


def decode_items(auctions: list[Auction]) -> list[Item | None]:
    """Decode each auction's item, or return None for a malformed one."""
    items: list[Item | None] = []
    for auction in auctions:
        try:
            items.append(decode_single(auction["item_bytes"]))
        except (ItemDecodeError, KeyError):  # fmt: skip
            items.append(None)
    return items


async def get_active_auctions(page: int = 0) -> AuctionPage:
    return validate_auctions(await http.get_json(ACTIVE_URL.format(page)))


async def get_ended_auctions() -> AuctionPage:
    return validate_auctions(await http.get_json(ENDED_URL))


async def make_auction_embed(auction: Auction, item: Item) -> disnake.Embed:
    tag = optional_compound(item, "tag")
    color = item_color(item)
    tier = auction.get("tier", "COMMON")
    embed = disnake.Embed(
        url=constants.AUCTION_URL.format(auction["uuid"]),
        title=auction["item_name"],
        color=color & 0xFFFFFF
        if color is not None
        else constants.RARITY_COLORS.get(tier)
        if isinstance(tier, str)
        else None,
    )
    damage = item.get("Damage")
    embed.set_thumbnail(
        utils.get_item_image(
            # The URL formats any id with str(), so convert it the same way.
            item_id=str(optional_compound(tag, "ExtraAttributes").get("id", "DIRT")),
            color=f"{color & 0xFFFFFF:06X}" if color is not None else None,
            durability=damage if isinstance(damage, int) else None,
        )
    )
    embed.set_footer(text="/viewauction " + auction_text(auction, "uuid"))
    embed.add_field(
        name="Price" if auction["bin"] else "Starting Bid",
        value=utils.numerize(auction_number(auction, "starting_bid")),
        inline=True,
    )
    if not auction["bin"]:
        embed.add_field(
            name="Auction End",
            value=f"<t:{auction_number(auction, 'end') // 1000}:R>",
            inline=True,
        )
    uuid = auction["auctioneer"]
    try:
        name = (await mojang.get(auction_text(auction, "auctioneer"))).name
    except Exception:
        # The alert matters more than the seller's name. Show the UUID instead.
        logger.warning("Cannot find the name of auctioneer %s.", uuid, exc_info=True)
        name = uuid
    embed.set_author(
        name=name,
        icon_url=constants.MC_HEAD_IMAGE.format(uuid),
        url=constants.STATS_URL.format(uuid),
    )
    return embed


class AHListener:
    def __init__(self, bot: SkypixelBot) -> None:
        self.bot: SkypixelBot = bot

    async def on_admin_spawned_auction(self, auction: Auction, item: Item) -> None:
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Origin Tag",
            value=compound(compound(item, "tag"), "ExtraAttributes")["originTag"],
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.ADMIN_SPAWNED_ITEMS_CHANNEL, embed=embed
        )

    async def on_og_reforge_auction(self, auction: Auction, item: Item) -> None:
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Reforge",
            value=compound(compound(item, "tag"), "ExtraAttributes")["modifier"],
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.OG_REFORGES_CHANNEL, embed=embed
        )

    async def on_semi_og_reforge_auction(self, auction: Auction, item: Item) -> None:
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Reforge",
            value=compound(compound(item, "tag"), "ExtraAttributes")["modifier"],
            inline=True,
        )
        await utils.notify_to_channel(
            self.bot, constants.SEMI_OG_REFORGES_CHANNEL, embed=embed
        )

    async def on_poi_auction(self, auction: Auction, item: Item) -> None:
        rankname = utils.remove_color_codes(
            await ranktracker.get_rankname(auction_text(auction, "auctioneer"))
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
        self, auction: Auction, item: Item, timestamp: int
    ) -> None:
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
        self, auction: Auction, item: Item, hex_code: str
    ) -> None:
        embed = await make_auction_embed(auction, item)
        embed.add_field(name="Hex Code", value=f"#{hex_code}", inline=True)
        item_id = compound(compound(item, "tag"), "ExtraAttributes")["id"]
        if not isinstance(item_id, str):
            raise ValueError("The item id is not text.")
        armor_type = constants.SEYMOUR_IDS[item_id]
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
        auction: Auction,
        item: Item,
        exotic_type: colors.ExoticType,
        hex_code: str,
    ) -> None:
        embed = await make_auction_embed(auction, item)
        embed.add_field(name="Hex Code", value=f"#{hex_code}")
        embed.add_field(
            name="Exotic Type", value=exotic_type.replace("_", " ").title(), inline=True
        )
        send_tasks: list[Awaitable[disnake.Message | None]] = [
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

    async def on_cake_soul_auction(self, auction: Auction, item: Item) -> None:
        embed = await make_auction_embed(auction, item)
        damage = item.get("Damage")
        dye_data = (
            constants.MINECRAFT_DYES.get(damage) if isinstance(damage, int) else None
        )
        if dye_data:
            embed.title = dye_data["colorName"].title() + " Cake Soul"
            embed.color = dye_data["hex"]
        cake_owner = item_text(extra_attributes(item), "cake_owner") or "None"
        embed.add_field(
            name="Cake Owner", value=utils.remove_color_codes(cake_owner), inline=True
        )
        pings: list[str] = []
        if (
            auction["bin"]
            and auction_number(auction, "starting_bid") <= 7_500_000
            and dye_data
            and dye_data["colorName"] == "red"
        ):
            pings.append(f"<@&{constants.CHEAP_RED_SOUL_ROLE}>")
        if auction["bin"] and auction_number(auction, "starting_bid") <= 5_000_000:
            pings.append(f"<@&{constants.CHEAP_SOUL_ROLE}>")
        await utils.notify_to_channel(
            self.bot, constants.CAKE_SOUL_AUCTIONS_CHANNEL, " ".join(pings), embed=embed
        )

    async def on_editioned_auction(
        self,
        auction: Auction,
        item: Item,
        edition: int,
        timestamp: int | None,
    ) -> None:
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Edition", value=f"#{utils.commaize(edition)}", inline=True
        )
        recipient_name = item_text(extra_attributes(item), "recipient_name")
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
    interval: float = 15
    max_cursor_age: int = 10 * 60

    def __init__(self, bot: SkypixelBot) -> None:
        super().__init__(bot)
        self.active_uploads: UploadQueue = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "auctions"
        )
        self.ended_uploads: UploadQueue = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "ended_auctions"
        )
        # Save the scan cursors so a quick restart picks up where it stopped.
        # After a long outage, start fresh instead of alerting on every
        # auction made while the bot was down.
        self.cursors: JsonWrapper[int] = JsonWrapper(
            bot.settings.storage_dir / "auctions.json"
        )
        fresh = time.time() * 1000 - self.max_cursor_age * 1000
        self.last_scanned_active: int = self._load_cursor("active", fresh)
        self.last_scanned_ended: int = self._load_cursor("ended", fresh)
        self._scan_semaphore: asyncio.Semaphore = asyncio.Semaphore(20)
        self._late_polls: dict[str, int] = {"active": 0, "ended": 0}
        # Not "listener", which would hide disnake's Cog.listener decorator.
        self.alerts: AHListener = AHListener(bot)

    def _load_cursor(self, name: str, fresh: float) -> int:
        cursor: object = self.cursors.get(name)
        return cursor if isinstance(cursor, int) and cursor >= fresh else 0

    async def save_cursors(self) -> None:
        cursors = {"active": self.last_scanned_active, "ended": self.last_scanned_ended}
        if cursors != self.cursors.to_dict():
            await self.cursors.replace(cursors)

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

    async def upload_queue(self) -> None:
        await finish_tasks(self.active_uploads.flush(), self.ended_uploads.flush())

    def log_auction(self, auction: Auction, item: Item, ended: bool) -> None:
        # item_data is the decoded item_bytes, so storing both doubles the item.
        doc: Document = {
            key: value for key, value in auction.items() if key != "item_bytes"
        }
        doc["item_data"] = item
        if ended:
            doc["_id"] = doc.pop("auction_id")
            self.ended_uploads.append(doc)
        else:
            doc["_id"] = doc.pop("uuid")
            self.active_uploads.append(doc)

    async def on_auction(self, auction: Auction, item: Item, new: bool = True) -> None:
        self.log_auction(auction, item, ended=False)
        if not new:
            return
        attributes = extra_attributes(item)
        if not attributes.get("uuid"):
            return
        item_id = attributes.get("id")
        timestamp = item_timestamp(attributes)
        color = item_color(item)
        hex_code = f"{color & 0xFFFFFF:06X}" if color is not None else None
        exotic_type = (
            colors.get_exotic_type(item_id, hex_code)
            if isinstance(item_id, str)
            and item_id
            and hex_code
            and not attributes.get("dye_item")
            else None
        )
        edition = attributes.get("edition", attributes.get("basket_edition"))
        if edition and not isinstance(edition, int):
            raise ValueError("The item edition is not a number.")
        categories = auction.get("categories", [])
        accessory = auction.get("category") == "accessories" or (
            isinstance(categories, list) and "accessories" in categories
        )
        tasks: list[Awaitable[None]] = []

        if attributes.get("originTag") in constants.ADMIN_ORIGIN_TAGS:
            tasks.append(self.alerts.on_admin_spawned_auction(auction, item))
        if not accessory and attributes.get("modifier") in constants.OG_REFORGES:
            tasks.append(self.alerts.on_og_reforge_auction(auction, item))
        if accessory and attributes.get("modifier", "none") != "none":
            tasks.append(self.alerts.on_semi_og_reforge_auction(auction, item))
        if auction["auctioneer"] in ranktracker.POI_UUIDS:
            tasks.append(self.alerts.on_poi_auction(auction, item))
        if (
            timestamp
            and timestamp <= 1575910800
            and auction_number(auction, "starting_bid") <= 100_000_000
        ):
            tasks.append(self.alerts.on_old_item_auction(auction, item, timestamp))
        if item_id in constants.SEYMOUR_IDS and hex_code:
            tasks.append(self.alerts.on_seymour_auction(auction, item, hex_code))
        if exotic_type and hex_code:
            tasks.append(
                self.alerts.on_exotic_auction(auction, item, exotic_type, hex_code)
            )
        if item_id == "CAKE_SOUL":
            tasks.append(self.alerts.on_cake_soul_auction(auction, item))
        if isinstance(edition, int) and edition > 0:
            tasks.append(
                self.alerts.on_editioned_auction(auction, item, edition, timestamp)
            )
        if tasks:
            await finish_tasks(*tasks)

    async def on_auction_end(self, auction: Auction, item: Item) -> None:
        self.log_auction(auction, item, ended=True)

    async def process_auction(
        self,
        auction: Auction,
        item: Item | None,
        *,
        ended: bool = False,
        new: bool = True,
    ) -> None:
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
            except NotificationStorageError:
                raise
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
                and min(as_number(a.get("start", 0), "start") for a in page["auctions"])
                > self.last_scanned_active
            ):
                page = await get_active_auctions(len(pages))
                if page["lastUpdated"] != page_0["lastUpdated"]:
                    raise ValueError("The auction API changed snapshots between pages.")
                pages.append(page)
            decoded_pages: list[tuple[list[Auction], list[Item | None]]] = []
            for page in pages:
                auctions = [
                    a
                    for a in page["auctions"]
                    if as_number(
                        a.get("last_updated", a.get("start", 0)), "last_updated"
                    )
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
                            new=as_number(a.get("start", 0), "start")
                            >= self.last_scanned_active,
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
                if as_number(a.get("timestamp", 0), "timestamp")
                >= self.last_scanned_ended
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

    async def poll(self) -> float:
        delays = await asyncio.gather(
            self.active_scanner(), self.ended_scanner(), return_exceptions=True
        )
        try:
            await self.upload_queue()
        except Exception:
            # The queues keep failed batches, so the next poll retries them.
            # Scanning should keep its own schedule while MongoDB is down.
            logger.exception("Cannot upload auction records.")
        try:
            await self.save_cursors()
        except OSError:
            logger.exception("Cannot save the auction scan cursors.")
        for delay in delays:
            if isinstance(delay, BaseException):
                raise delay
        return min(delay for delay in delays if not isinstance(delay, BaseException))

    async def close_resources(self) -> None:
        await finish_tasks(self.active_uploads.close(), self.ended_uploads.close())
