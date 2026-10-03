import logging
from typing import Any

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.settings import settings
from skypixel.storage.json import JsonWrapper
from skypixel.storage.mongo import UploadQueue
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)
URL: str = "https://api.hypixel.net/v2/skyblock/firesales"


async def get_fire_sales() -> dict[str, dict[str, Any]]:
    data = await http.get_json(URL)
    if not isinstance(data, dict) or not isinstance(data.get("sales"), list):
        raise ValueError("The fire sale API did not return a sales list.")
    return {
        sale["item_id"]: {key: value for key, value in sale.items() if key != "item_id"}
        for sale in data["sales"]
    }


async def send(embeds: list[disnake.Embed]):
    await utils.broadcast(constants.FIRE_SALE_TRACKER_CHANNELS, embeds=embeds)


class FireSaleTrackerCog(PollingCog):
    interval = 120

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(settings.storage_dir / "firesales.json")
        self.uploads = UploadQueue("SkyBlock", "firesales")

    def log_firesale(self, item_id: str, sale: dict[str, Any]):
        doc = sale.copy()
        doc["_id"] = item_id
        self.uploads.append(doc)

    @staticmethod
    def make_fire_sale_embed(item_id: str, sale: dict[str, Any]) -> disnake.Embed:
        embed = utils.add_footer(
            disnake.Embed(
                title="New Fire Sale Added!",
                description="\n".join(
                    [
                        f"**Item ID:** `{item_id}`",
                        f"**Amount:** `{sale['amount']}`",
                        f"**Price:** `{sale['price']}`",
                        f"**Starts:** <t:{sale['start'] // 1000}> (<t:{sale['start'] // 1000}:R>)",
                        f"**Ends:** <t:{sale['end'] // 1000}> (<t:{sale['end'] // 1000}:R>)",
                    ]
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        embed.set_thumbnail(url=utils.get_item_image(item_id))
        return embed

    async def poll(self):
        embeds: list[disnake.Embed] = []
        sales = await get_fire_sales()
        initialized = bool(self.data)
        new_sales = {}
        for item_id, sale in sales.items():
            self.log_firesale(item_id, sale)
            if item_id not in self.data:
                if initialized:
                    embeds.append(self.make_fire_sale_embed(item_id, sale))
                new_sales[item_id] = sale
        if embeds:
            await send(embeds)
        if new_sales:
            self.data.update(new_sales)
            await self.data.save()
        await self.uploads.flush()

    async def close_resources(self):
        await self.uploads.close()
