import asyncio
import traceback
from typing import Any

import disnake
from disnake.ext import commands

import constants
from modules import asyncreqs
from modules import datamanager
from modules import utils

URL: str = "https://api.hypixel.net/v2/skyblock/firesales"


async def get_fire_sales() -> dict[str, dict[str, Any]]:
    response = await asyncreqs.get(URL)
    data = await response.json()
    sales = data.get('sales', [])
    return {sale.pop('item_id'): sale for sale in sales}


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.FIRE_SALE_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class FireSaleTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/firesales.json")

    async def on_fire_sale(self, item_id: str, sale: dict[str, Any]):
        embed = utils.add_footer(disnake.Embed(
            title="New Fire Sale Added!",
            description='\n'.join([
                f"**Item ID:** `{item_id}`",
                f"**Amount:** `{sale['amount']}`",
                f"**Price:** `{sale['price']}`",
                f"**Starts:** <t:{sale['start']//1000}> (<t:{sale['start']//1000}:R>)",
                f"**Ends:** <t:{sale['end']//1000}> (<t:{sale['end']//1000}:R>)"
            ]),
            color=constants.DEFAULT_EMBED_COLOR
        ))
        await send(embed)

    async def main(self):
        while True:
            try:
                sales = await get_fire_sales()
                for item_id, sale in sales.items():
                    if item_id not in self.data:
                        if self.data.to_dict():
                            await self.on_fire_sale(item_id, sale)
                        self.data[item_id] = sale
                        await self.data.save()
                    
                await asyncio.sleep(120)
            except Exception:
                print("fire sale tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())
