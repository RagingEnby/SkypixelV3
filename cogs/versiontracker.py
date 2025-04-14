import asyncio
import logging
import traceback

import disnake
from disnake.ext import commands

import constants
from modules import asyncreqs
from modules import datamanager
from modules import utils

logger = logging.getLogger(__name__)
URL: str = "https://api.hypixel.net/v2/resources/skyblock/skills"


async def get_version() -> str:
    response = await asyncreqs.get(URL)
    data = await response.json()
    version = data.get('version')
    if not version:
        logger.error('malformed skills data:', data)
        await asyncio.sleep(10)
        return await get_version()
    logger.debug("got version:", version)
    return version


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.VERSION_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class VersionTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/version.json")
        if not self.data.get('version'):
            logger.warning("version.json is empty")

    @staticmethod
    async def on_version_change(before: str, after: str):
        embed = utils.add_footer(disnake.Embed(
            title="SkyBlock has updated!",
            description=f"`{before}` ➡ `{after}`",
            color=constants.DEFAULT_EMBED_COLOR
        ))
        await send(embed)

    async def main(self):
        while True:
            try:
                version = await get_version()
                if version != self.data.get('version'):
                    logger.info("version update:", self.data.get('version'), "=>", version)
                    if self.data.get('version'):
                        await self.on_version_change(self.data['version'], version)
                    self.data['version'] = version
                    await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(120)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
