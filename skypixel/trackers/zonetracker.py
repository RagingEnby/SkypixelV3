from skypixel.trackers.base import PollingCog

import asyncio
import logging

import disnake
from disnake.ext import commands

from skypixel import constants
from skypixel.clients import http as asyncreqs
from skypixel.storage import json as datamanager
from skypixel import discord as utils

URL: str = "https://api.ragingenby.dev/skyblock/zones"
logger = logging.getLogger(__name__)


async def get_zones() -> set[str]:
    data = await asyncreqs.get_json(URL)
    if not isinstance(data, dict) or not isinstance(data.get("zones"), list):
        raise ValueError("The zone API did not return a zones list.")
    return set(data["zones"])


async def send(embed: disnake.Embed):
    await utils.broadcast(constants.ZONE_TRACKER_CHANNELS, embed=embed)


class ZoneTrackerCog(PollingCog):
    interval = 12000

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = datamanager.JsonWrapper(constants.STORAGE_DIR / "zones.json")
        if not self.data.get("zones"):
            logger.warning("zones.json is empty")
            self.data["zones"] = []

    @staticmethod
    async def on_new_zone(zones: set[str]):
        logger.debug(f"new zones detected: {zones}")
        embed = utils.add_footer(
            disnake.Embed(
                title="New SkyBlock Zone Added!",
                description="New areas/zones have been added to SkyBlock's API.\n```\n{}\n```".format(
                    "\n".join(zones)
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        await send(embed)

    async def poll(self):
        zones = await get_zones()
        new = {zone for zone in zones if zone not in self.data["zones"]}
        if new:
            if self.data.get("zones"):
                await self.on_new_zone(new)
            self.data["zones"].extend(new)
            await self.data.save()

    async def close_resources(self):
        logger.debug("closing...")
