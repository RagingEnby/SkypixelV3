import logging
from typing import TYPE_CHECKING

import disnake

from skypixel import constants, subscriptions, utils
from skypixel.clients import http
from skypixel.storage.json_store import JsonWrapper
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


URL: str = "https://api.ragingenby.dev/hypixel/skyblock/zones"
logger = logging.getLogger(__name__)


async def get_zones() -> set[str]:
    data = await http.get_json(URL)
    if not isinstance(data, dict) or not isinstance(data.get("zones"), list):
        raise ValueError("The zone API did not return a zones list.")
    return set(data["zones"])


async def send(bot: SkypixelBot, embed: disnake.Embed):
    await utils.broadcast(bot, subscriptions.current().zone, embed=embed)


class ZoneTrackerCog(PollingCog):
    interval = 12000

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "zones.json")
        if not self.data.get("zones"):
            logger.warning("zones.json is empty")
            self.data["zones"] = []

    async def on_new_zone(self, zones: set[str]):
        logger.debug("new zones detected: %s", zones)
        embed = utils.add_footer(
            disnake.Embed(
                title="New SkyBlock Zone Added!",
                description="New areas/zones have been added to SkyBlock's API.\n```\n{}\n```".format(
                    "\n".join(zones)
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        await send(self.bot, embed)

    async def poll(self):
        zones = await get_zones()
        new = {zone for zone in zones if zone not in self.data["zones"]}
        if new:
            if self.data.get("zones"):
                await self.on_new_zone(new)
            await self.data.replace(
                {**self.data, "zones": self.data["zones"] + sorted(new)}
            )
