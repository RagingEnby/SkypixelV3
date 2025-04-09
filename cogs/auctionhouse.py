from typing import Any
import disnake
from disnake.ext import commands
import asyncio
import traceback
import time

from modules import asyncreqs
from modules import datamanager
from modules import utils

import constants


ACTIVE_URL: str = "https://api.hypixel.net/v2/skyblock/auctions?page=0"


async def get_active_auctions() -> dict[str, Any]:
    response = await asyncreqs.get(ACTIVE_URL)
    if response.status != 200:
        print('/skyblock/auctions returned', response.status)
        await asyncio.sleep(5)
        return await get_active_auctions()
    return await response.json()


class AuctionTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None

    async def on_auction(self, auction: dict[str, Any]):
        return

    async def main(self):
        last_last_updated = 0
        while True:
            try:
                page_0 = await get_active_auctions()
                if page_0['lastUpdated'] != last_last_updated:
                    print(page_0['lastUpdated'], '!=', last_last_updated)
                    new_auctions = [
                        a for a in page_0['auctions']
                        if a.get('start', 0) >= last_last_updated
                    ]
                    print(f'got {len(new_auctions)} new auctions')
                    await asyncio.gather(*[self.on_auction(a) for a in new_auctions])
                    last_last_updated = page_0['lastUpdated']
                next_update = last_last_updated // 1000 + 60
                time_until_update = next_update - time.time()
                if time_until_update <= 0:
                    time_until_update = 1
                print('waiting', time_until_update)
                await asyncio.sleep(time_until_update)
            except Exception:
                print("AH tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())
