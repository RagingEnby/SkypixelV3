import logging
import time
from typing import TYPE_CHECKING

import disnake

from skypixel import constants, utils
from skypixel.clients import http, hypixel
from skypixel.domain.types import JSON
from skypixel.storage.database import Alert, TrackerState
from skypixel.storage.mongo import UploadQueue
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger: logging.Logger = logging.getLogger(__name__)
URL: str = "https://api.hypixel.net/v2/skyblock/firesales"

# One fire sale without its item_id, such as {"amount": 1, "price": 100, ...}.
type FireSale = dict[str, JSON]


def _sale_items(sales: list[JSON]) -> list[dict[str, JSON]]:
    if not all(isinstance(sale, dict) for sale in sales):
        raise ValueError("The fire sale API did not return a sales list.")
    return [sale for sale in sales if isinstance(sale, dict)]


def _item_id(sale: dict[str, JSON]) -> str:
    item_id = sale["item_id"]
    if not isinstance(item_id, str):
        raise ValueError("A fire sale has no item id.")
    return item_id


def _sale_number(sale: FireSale, key: str) -> int | float:
    value = sale[key]
    if not isinstance(value, int | float):
        raise ValueError(f"The fire sale {key} is not a number.")
    return value


async def get_fire_sales() -> dict[str, FireSale]:
    data = await http.get_json(URL)
    sales = data.get("sales") if isinstance(data, dict) else None
    if not isinstance(sales, list):
        raise ValueError("The fire sale API did not return a sales list.")
    return {
        _item_id(sale): {key: value for key, value in sale.items() if key != "item_id"}
        for sale in _sale_items(sales)
    }


def send(embeds: list[disnake.Embed]) -> list[Alert]:
    return utils.broadcast(constants.FIRE_SALE_TRACKER_CHANNELS, embeds=embeds)


class FireSaleTrackerCog(PollingCog):
    interval: float = 120

    def __init__(self, bot: SkypixelBot) -> None:
        super().__init__(bot)
        self.data: TrackerState[FireSale] = TrackerState(bot.database, "firesales")
        self.uploads: UploadQueue = UploadQueue(
            bot.settings.mongodb_uri, "SkyBlock", "firesales"
        )
        # Ended sales are pruned, so empty state does not mean the first run.
        # Only missing state does.
        self.initialized: bool = self.data.exists

    def log_firesale(self, item_id: str, sale: FireSale) -> None:
        doc = sale.copy()
        doc["_id"] = item_id
        self.uploads.append(doc)

    @staticmethod
    def make_fire_sale_embed(item_id: str, sale: FireSale) -> disnake.Embed:
        try:
            item = f"{hypixel.get_name(item_id)} (`{item_id}`)"
        except (KeyError, ValueError):  # fmt: skip
            item = f"`{item_id}`"
        amount = _sale_number(sale, "amount")
        price = _sale_number(sale, "price")
        start = _sale_number(sale, "start")
        end = _sale_number(sale, "end")
        embed = utils.add_footer(
            disnake.Embed(
                title="New Fire Sale Added!",
                description="\n".join(
                    [
                        f"**Item:** {item}",
                        f"**Amount:** `{utils.commaize(amount)}`",
                        f"**Price:** `{utils.commaize(price)}` gems",
                        f"**Starts:** <t:{start // 1000}> (<t:{start // 1000}:R>)",
                        f"**Ends:** <t:{end // 1000}> (<t:{end // 1000}:R>)",
                    ]
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        embed.set_thumbnail(url=utils.get_item_image(item_id))
        return embed

    async def poll(self) -> None:
        embeds: list[disnake.Embed] = []
        sales = await get_fire_sales()
        initialized = self.initialized or bool(self.data)
        new_sales: dict[str, FireSale] = {}
        for item_id, sale in sales.items():
            self.log_firesale(item_id, sale)
            if item_id not in self.data:
                if initialized:
                    embeds.append(self.make_fire_sale_embed(item_id, sale))
                new_sales[item_id] = sale
        alerts = send(embeds) if embeds else []
        # Forget ended sales so a later sale of the same item is announced.
        now = time.time() * 1000
        kept = {
            item_id: sale
            for item_id, sale in self.data.items()
            if item_id in sales
            or not isinstance(end := sale.get("end"), int | float)
            or end > now
        }
        if new_sales or len(kept) != len(self.data) or not self.initialized:
            await self.data.replace({**kept, **new_sales}, alerts)
            self.initialized = True
        await self.uploads.flush()

    async def close_resources(self) -> None:
        await self.uploads.close()
