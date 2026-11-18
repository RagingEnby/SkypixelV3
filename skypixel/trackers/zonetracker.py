import logging
from typing import TYPE_CHECKING

import disnake

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.storage.database import Alert, TrackerState
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


def send(embed: disnake.Embed) -> list[Alert]:
    return utils.broadcast(constants.ZONE_TRACKER_CHANNELS, embed=embed)


class ZoneTrackerCog(PollingCog):
    interval: float = 12000

    def __init__(self, bot: SkypixelBot) -> None:
        super().__init__(bot)
        self.data: TrackerState[list[str]] = TrackerState(bot.database, "zones")
        if not self.data.get("zones"):
            logger.warning("The saved zone list is empty.")
            self.data["zones"] = []

    def on_new_zone(self, zones: set[str]) -> list[Alert]:
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
        return send(embed)

    async def poll(self) -> None:
        zones = await get_zones()
        new = {zone for zone in zones if zone not in self.data["zones"]}
        if new:
            alerts = self.on_new_zone(new) if self.data.get("zones") else []
            await self.data.replace(
                {**self.data, "zones": self.data["zones"] + sorted(new)}, alerts
            )
