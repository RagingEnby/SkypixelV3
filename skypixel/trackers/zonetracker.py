import logging
from typing import TYPE_CHECKING

import disnake

from skypixel import alerts, constants, embed_utils
from skypixel.clients import http
from skypixel.storage.json_store import JsonWrapper
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


URL: str = "https://api.ragingenby.dev/hypixel/skyblock/zones"
logger: logging.Logger = logging.getLogger(__name__)


async def get_zones() -> set[str]:
    data = await http.get_json(URL)
    zones = data.get("zones") if isinstance(data, dict) else None
    if not isinstance(zones, list) or not all(isinstance(zone, str) for zone in zones):
        raise ValueError("The zone API did not return a zones list.")
    return {zone for zone in zones if isinstance(zone, str)}


async def send(bot: SkypixelBot, embed: disnake.Embed) -> None:
    await alerts.broadcast(bot, constants.ZONE_TRACKER_CHANNELS, embed=embed)


class ZoneTrackerCog(PollingCog):
    interval: float = 12000

    def __init__(self, bot: SkypixelBot) -> None:
        super().__init__(bot)
        self.data: JsonWrapper[list[str]] = JsonWrapper(
            bot.settings.storage_dir / "zones.json"
        )
        if not self.data.get("zones"):
            logger.warning("zones.json is empty")
            self.data["zones"] = []

    async def on_new_zone(self, zones: set[str]) -> None:
        logger.debug("new zones detected: %s", zones)
        embed = embed_utils.add_footer(
            disnake.Embed(
                title="New SkyBlock Zone Added!",
                description="New areas/zones have been added to SkyBlock's API.\n```\n{}\n```".format(
                    "\n".join(zones)
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        await send(self.bot, embed)

    async def poll(self) -> None:
        zones = await get_zones()
        new = {zone for zone in zones if zone not in self.data["zones"]}
        if new:
            if self.data.get("zones"):
                await self.on_new_zone(new)
            await self.data.replace(
                {**self.data, "zones": self.data["zones"] + sorted(new)}
            )
