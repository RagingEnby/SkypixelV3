import logging
import time
from pathlib import Path
from typing import Any

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http, hypixel
from skypixel.storage.json_store import JsonWrapper
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


async def send(bot: commands.InteractionBot, embeds: list[disnake.Embed]):
    await utils.broadcast(bot, constants.FIRE_SALE_TRACKER_CHANNELS, embeds=embeds)


class FireSaleTrackerCog(PollingCog):
    interval = 120

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "firesales.json")
        self.uploads = UploadQueue(bot.settings.mongodb_uri, "SkyBlock", "firesales")
        # Ended sales are pruned, so an empty file does not mean the first run.
        self.initialized = Path(self.data.file_path).exists()

    def log_firesale(self, item_id: str, sale: dict[str, Any]):
        doc = sale.copy()
        doc["_id"] = item_id
        self.uploads.append(doc)

    @staticmethod
    def make_fire_sale_embed(item_id: str, sale: dict[str, Any]) -> disnake.Embed:
        try:
            item = f"{hypixel.get_name(item_id)} (`{item_id}`)"
        except (KeyError, ValueError):  # fmt: skip
            item = f"`{item_id}`"
        embed = utils.add_footer(
            disnake.Embed(
                title="New Fire Sale Added!",
                description="\n".join(
                    [
                        f"**Item:** {item}",
                        f"**Amount:** `{utils.commaize(sale['amount'])}`",
                        f"**Price:** `{utils.commaize(sale['price'])}` gems",
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
        initialized = self.initialized or bool(self.data)
        new_sales = {}
        for item_id, sale in sales.items():
            self.log_firesale(item_id, sale)
            if item_id not in self.data:
                if initialized:
                    embeds.append(self.make_fire_sale_embed(item_id, sale))
                new_sales[item_id] = sale
        if embeds:
            await send(self.bot, embeds)
        # Forget ended sales so a later sale of the same item is announced.
        now = time.time() * 1000
        kept = {
            item_id: sale
            for item_id, sale in self.data.items()
            if item_id in sales
            or not isinstance(sale.get("end"), int | float)
            or sale["end"] > now
        }
        if new_sales or len(kept) != len(self.data) or not self.initialized:
            await self.data.replace({**kept, **new_sales})
            self.initialized = True
        await self.uploads.flush()

    async def close_resources(self):
        await self.uploads.close()
