from skypixel.trackers.base import PollingCog

import asyncio
import logging
from typing import Any

import disnake
from disnake.ext import commands

from skypixel import constants
from skypixel.clients import http as asyncreqs
from skypixel.storage import json as datamanager
from skypixel.storage import mongo as mongodb
from skypixel import discord as utils

logger = logging.getLogger(__name__)
URL: str = "https://api.hypixel.net/v2/skyblock/firesales"


async def get_fire_sales() -> dict[str, dict[str, Any]]:
    data = await asyncreqs.get_json(URL)
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
        self.data = datamanager.JsonWrapper(constants.STORAGE_DIR / "firesales.json")
        self.db: mongodb.Collection | None = None
        self.db_queue = []

    async def upload_queue(self):
        if not self.db_queue:
            return
        if not self.db:
            self.db = mongodb.Collection("SkyBlock", "firesales")
        await mongodb.flush_queue(self.db, self.db_queue)

    def log_firesale(self, item_id: str, sale: dict[str, Any]):
        doc = sale.copy()
        doc["_id"] = item_id
        self.db_queue.append(doc)

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
        changed = False
        for item_id, sale in sales.items():
            self.log_firesale(item_id, sale)
            if item_id not in self.data:
                if initialized:
                    embeds.append(self.make_fire_sale_embed(item_id, sale))
                self.data[item_id] = sale
                changed = True
        if embeds:
            await send(embeds)
        if changed:
            await self.data.save()
        await self.upload_queue()

    async def close_resources(self):
        if self.db:
            await self.db.close()
            self.db = None
