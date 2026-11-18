import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import disnake

from skypixel import alerts, constants, embed_utils, formatting
from skypixel.clients import http, mojang
from skypixel.domain import colors
from skypixel.domain.nbt import ItemDecodeError, decode_single
from skypixel.storage.json_store import JsonWrapper
from skypixel.storage.mongo import UploadQueue
from skypixel.storage.notifications import NotificationStorageError
from skypixel.trackers import ranktracker
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


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
    color = display.get("color")
    embed = disnake.Embed(
        url=constants.AUCTION_URL.format(auction["uuid"]),
        title=auction["item_name"],
        color=color & 0xFFFFFF
        if color is not None
        else constants.RARITY_COLORS.get(auction.get("tier", "COMMON")),
    )
    embed.set_thumbnail(
        embed_utils.get_item_image(
            item_id=tag.get("ExtraAttributes", {}).get("id", "DIRT"),
            color=f"{color & 0xFFFFFF:06X}" if color is not None else None,
            durability=item.get("Damage"),
        )
    )
    embed.set_footer(text="/viewauction " + auction["uuid"])
    embed.add_field(
        name="Price" if auction["bin"] else "Starting Bid",
        value=formatting.numerize(auction["starting_bid"]),
        inline=True,
    )
    if not auction["bin"]:
        embed.add_field(
            name="Auction End", value=f"<t:{auction['end'] // 1000}:R>", inline=True
        )
    uuid = auction["auctioneer"]
    try:
        name = (await mojang.get(uuid)).name
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


@dataclass(frozen=True)
class AuctionInfo:
    """The fields of an auction that the alert rules read."""

    auction: dict[str, Any]
    item: dict[str, Any]
    extra_attributes: dict[str, Any]
    item_id: str | None
    timestamp: int | None
    hex_code: str | None
    exotic_type: colors.ExoticType | None
    edition: int | None
    accessory: bool

    @classmethod
    def read(cls, auction: dict[str, Any], item: dict[str, Any]) -> AuctionInfo:
        extra_attributes = item.get("tag", {}).get("ExtraAttributes", {})
        item_id = extra_attributes.get("id")
        color = item.get("tag", {}).get("display", {}).get("color")
        hex_code = f"{color & 0xFFFFFF:06X}" if color is not None else None
        return cls(
            auction=auction,
            item=item,
            extra_attributes=extra_attributes,
            item_id=item_id,
            timestamp=formatting.normalize_timestamp(extra_attributes["timestamp"])
            if extra_attributes.get("timestamp")
            else None,
            hex_code=hex_code,
            exotic_type=colors.get_exotic_type(item_id, hex_code)
            if item_id and hex_code and not extra_attributes.get("dye_item")
            else None,
            edition=extra_attributes.get(
                "edition", extra_attributes.get("basket_edition")
            ),
            accessory=auction.get("category") == "accessories"
            or "accessories" in auction.get("categories", []),
        )


async def add_origin_tag(embed: disnake.Embed, info: AuctionInfo) -> None:
    embed.add_field(
        name="Origin Tag", value=info.extra_attributes["originTag"], inline=True
    )


async def add_reforge(embed: disnake.Embed, info: AuctionInfo) -> None:
    embed.add_field(
        name="Reforge", value=info.extra_attributes["modifier"], inline=True
    )


async def show_rankname(embed: disnake.Embed, info: AuctionInfo) -> None:
    rankname = formatting.remove_color_codes(
        await ranktracker.get_rankname(info.auction["auctioneer"])
    )
    embed.set_author(
        name=rankname,
        icon_url=constants.MC_HEAD_IMAGE.format(info.auction["auctioneer"]),
    )


async def add_created_at(embed: disnake.Embed, info: AuctionInfo) -> None:
    embed.add_field(
        name="Created At",
        value=f"<t:{info.timestamp}>\n-# <t:{info.timestamp}:R>",
        inline=True,
    )


async def add_seymour_matches(embed: disnake.Embed, info: AuctionInfo) -> None:
    assert info.hex_code is not None
    embed.add_field(name="Hex Code", value=f"#{info.hex_code}", inline=True)
    armor_type = constants.SEYMOUR_IDS[info.extra_attributes["id"]]
    top_5 = colors.get_top_5(armor_type, info.hex_code)
    embed.description = (
        "```\n" + "\n".join([f"{k}: {round(v, 2)}" for k, v in top_5.items()]) + "```"
    )


async def add_exotic_type(embed: disnake.Embed, info: AuctionInfo) -> None:
    assert info.exotic_type is not None
    embed.add_field(name="Hex Code", value=f"#{info.hex_code}")
    embed.add_field(
        name="Exotic Type",
        value=info.exotic_type.replace("_", " ").title(),
        inline=True,
    )


async def describe_cake_soul(embed: disnake.Embed, info: AuctionInfo) -> str:
    auction, item = info.auction, info.item
    damage = item.get("Damage")
    dye_data = constants.MINECRAFT_DYES.get(damage) if isinstance(damage, int) else None
    if dye_data:
        embed.title = dye_data["colorName"].title() + " Cake Soul"
        embed.color = dye_data["hex"]
    cake_owner = info.extra_attributes.get("cake_owner") or "None"
    embed.add_field(
        name="Cake Owner",
        value=formatting.remove_color_codes(cake_owner),
        inline=True,
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
    return " ".join(pings)


async def add_edition(embed: disnake.Embed, info: AuctionInfo) -> None:
    assert info.edition is not None
    embed.add_field(
        name="Edition", value=f"#{formatting.commaize(info.edition)}", inline=True
    )
    recipient_name = info.extra_attributes.get("recipient_name")
    if recipient_name:
        embed.add_field(
            name="Recipient Name",
            value=formatting.esc_mrkdwn(formatting.remove_color_codes(recipient_name)),
            inline=True,
        )
    if info.timestamp:
        await add_created_at(embed, info)


def exotic_thread(info: AuctionInfo) -> tuple[int, int] | None:
    assert info.exotic_type is not None
    thread_id = constants.EXOTIC_AUCTIONS_THREADS.get(info.exotic_type)
    if not thread_id:
        return None
    return constants.EXOTIC_AUCTIONS_THREADS_PARENT, thread_id


@dataclass(frozen=True)
class Rule:
    """One auction alert: when it fires, where it goes, and what it adds.

    decorate changes the shared auction embed and may return the message
    text, such as role pings. thread returns an extra (parent channel, thread)
    destination for the same message.
    """

    name: str
    matches: Callable[[AuctionInfo], Any]
    channel: int
    decorate: Callable[[disnake.Embed, AuctionInfo], Awaitable[str | None]]
    thread: Callable[[AuctionInfo], tuple[int, int] | None] | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        "admin_spawned",
        lambda info: (
            info.extra_attributes.get("originTag") in constants.ADMIN_ORIGIN_TAGS
        ),
        constants.ADMIN_SPAWNED_ITEMS_CHANNEL,
        add_origin_tag,
    ),
    Rule(
        "og_reforge",
        lambda info: (
            not info.accessory
            and info.extra_attributes.get("modifier") in constants.OG_REFORGES
        ),
        constants.OG_REFORGES_CHANNEL,
        add_reforge,
    ),
    Rule(
        "semi_og_reforge",
        lambda info: (
            info.accessory and info.extra_attributes.get("modifier", "none") != "none"
        ),
        constants.SEMI_OG_REFORGES_CHANNEL,
        add_reforge,
    ),
    Rule(
        "poi",
        lambda info: info.auction["auctioneer"] in ranktracker.POI_UUIDS,
        constants.POI_AUCTIONS_CHANNEL,
        show_rankname,
    ),
    Rule(
        "old_item",
        lambda info: (
            info.timestamp
            and info.timestamp <= 1575910800
            and info.auction["starting_bid"] <= 100_000_000
        ),
        constants.OLD_ITEM_AUCTIONS_CHANNEL,
        add_created_at,
    ),
    Rule(
        "seymour",
        lambda info: info.item_id in constants.SEYMOUR_IDS and info.hex_code,
        constants.SEYMOUR_AUCTIONS_CHANNEL,
        add_seymour_matches,
    ),
    Rule(
        "exotic",
        lambda info: info.exotic_type and info.hex_code,
        constants.EXOTIC_AUCTIONS_CHANNEL,
        add_exotic_type,
        thread=exotic_thread,
    ),
    Rule(
        "cake_soul",
        lambda info: info.item_id == "CAKE_SOUL",
        constants.CAKE_SOUL_AUCTIONS_CHANNEL,
        describe_cake_soul,
    ),
    Rule(
        "editioned",
        lambda info: info.edition and info.edition > 0,
        constants.EDITIONED_AUCTIONS_CHANNEL,
        add_edition,
    ),
)


async def send_alert(bot: SkypixelBot, rule: Rule, info: AuctionInfo) -> None:
    embed = await make_auction_embed(info.auction, info.item)
    content = await rule.decorate(embed, info)
    sends = [alerts.notify_to_channel(bot, rule.channel, content, embed=embed)]
    thread = rule.thread(info) if rule.thread is not None else None
    if thread is not None:
        parent, thread_id = thread
        sends.append(
            alerts.notify_to_channel(
                bot, parent, content, thread_id=thread_id, embed=embed
            )
        )
    await finish_tasks(*sends)


class AuctionTrackerCog(PollingCog):
    interval = 15
    max_cursor_age = 10 * 60

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.active_uploads = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "auctions"
        )
        self.ended_uploads = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "ended_auctions"
        )
        # Save the scan cursors so a quick restart picks up where it stopped.
        # After a long outage, start fresh instead of alerting on every
        # auction made while the bot was down.
        self.cursors = JsonWrapper(bot.settings.storage_dir / "auctions.json")
        fresh = time.time() * 1000 - self.max_cursor_age * 1000
        self.last_scanned_active = self._load_cursor("active", fresh)
        self.last_scanned_ended = self._load_cursor("ended", fresh)
        self._scan_semaphore = asyncio.Semaphore(20)
        self._late_polls = {"active": 0, "ended": 0}

    def _load_cursor(self, name: str, fresh: float) -> int:
        cursor = self.cursors.get(name)
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

    async def upload_queue(self):
        await finish_tasks(self.active_uploads.flush(), self.ended_uploads.flush())

    def log_auction(self, auction: dict[str, Any], item: dict[str, Any], ended: bool):
        # item_data is the decoded item_bytes, so storing both doubles the item.
        doc = {key: value for key, value in auction.items() if key != "item_bytes"}
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
        if not item.get("tag", {}).get("ExtraAttributes", {}).get("uuid"):
            return
        info = AuctionInfo.read(auction, item)
        tasks = [
            send_alert(self.bot, rule, info) for rule in RULES if rule.matches(info)
        ]
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
                and min(a.get("start", 0) for a in page["auctions"])
                > self.last_scanned_active
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
        try:
            await self.save_cursors()
        except OSError:
            logger.exception("Cannot save the auction scan cursors.")
        for delay in delays:
            if isinstance(delay, BaseException):
                raise delay
        return min(delay for delay in delays if not isinstance(delay, BaseException))

    async def close_resources(self):
        await finish_tasks(self.active_uploads.close(), self.ended_uploads.close())
