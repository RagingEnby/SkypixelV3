import disnake
from disnake.ext import commands
import asyncio
import traceback

from modules import asyncreqs
from modules import datamanager
from modules import utils

import constants


URL: str = "https://api.ragingenby.dev/skyblock/zones"


async def get_zones() -> set[str]:
    response = await asyncreqs.get(URL)
    data = await response.json()
    return set(data['zones'])


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.ZONE_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class ZoneTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/zones.json")
        if not self.data.get('zones'):
            self.data['zones'] = []

    async def on_new_zone(self, zones: set[str]):
        embed = utils.add_footer(disnake.Embed(
            title="New SkyBlock Zone Added!",
            description="New areas/zones have been added to SkyBlock's API.\n```\n{}\n```".format('\n'.join(zones)),
            color=constants.DEFAULT_EMBED_COLOR
        ))
        await send(embed)

    async def main(self):
        while True:
            try:
                zones = await get_zones()
                new = {zone for zone in zones if zone not in self.data['zones']}
                if new:
                    await self.on_new_zone(new)
                    self.data['zones'].extend(new)
                    await self.data.save()
                await asyncio.sleep(12000)
            except Exception:
                print("version tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())
