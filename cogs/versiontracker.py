import disnake
from disnake.ext import commands
import asyncio
import traceback

from modules import asyncreqs
from modules import datamanager
from modules import utils

import constants


URL: str = "https://api.hypixel.net/v2/resources/skyblock/skills"


async def get_version() -> str:
    response = await asyncreqs.get(URL)
    data = await response.json()
    version = data.get('version')
    if not version:
        print('malformed skills data:', data)
        await asyncio.sleep(10)
        return await get_version()
    return version


class VersionTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.data = datamanager.JsonWrapper("storage/version.json")

    async def on_version_change(self, before: str, after: str):
        embed = disnake.Embed(
            title="SkyBlock has updated!",
            description=f"`{before}` ➡ `{after}`",
            color=constants.DEFAULT_EMBED_COLOR
        )
        embed = utils.add_footer(embed)
        await utils.send_to_channel(
            constants.VERSION_TRACKER_CHANNEL,
            constants.VERSION_TRACKER_PING,
            embed=embed
        )

    async def main(self):
        while True:
            try:
                version = await get_version()
                if version != self.data.get('version'):
                    await self.on_version_change(self.data.get('version'), version)
                    self.data['version'] = version
                    await self.data.save()
                await asyncio.sleep(120)
            except Exception:
                print("version tracker error:", traceback.format_exc())
    