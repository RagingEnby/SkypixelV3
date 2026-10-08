import logging

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.storage.json import JsonWrapper
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)
URL: str = "https://api.hypixel.net/v2/resources/skyblock/skills"


async def get_version() -> str:
    data = await http.get_json(URL)
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("The skills API did not return a version.")
    logger.debug("got version: %s", version)
    return version


async def send(embed: disnake.Embed):
    await utils.broadcast(constants.VERSION_TRACKER_CHANNELS, embed=embed)


class VersionTrackerCog(PollingCog):
    interval = 120

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "version.json")
        if not self.data.get("version"):
            logger.warning("version.json is empty")

    @staticmethod
    async def on_version_change(before: str, after: str):
        embed = utils.add_footer(
            disnake.Embed(
                title="SkyBlock has updated!",
                description=f"`{before}` ➡ `{after}`",
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        await send(embed)

    async def poll(self):
        version = await get_version()
        if version != self.data.get("version"):
            logger.debug("version update: %s => %s", self.data.get("version"), version)
            if self.data.get("version"):
                await self.on_version_change(self.data["version"], version)
            await self.data.replace({**self.data, "version": version})
