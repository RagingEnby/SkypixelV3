import disnake
from disnake.ext import commands
import asyncio
import traceback

from modules import asyncreqs
from modules import datamanager

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
            color=constants.DEFAULT_EMBED_COLOR
        )

    async def main(self):
        while True:
            try:
                version = await get_version()
                if version != self.data['version']:
                    await self.on_version_change(self.data['version'], version)
                    self.data['version'] = version
                    await self.data.save()
                await asyncio.sleep(60)
            except Exception as e:
                print("version tracker error:", traceback.format_exc())
    