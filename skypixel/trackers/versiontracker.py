import logging
from typing import TYPE_CHECKING

import disnake

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.storage.database import Alert, TrackerState
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger: logging.Logger = logging.getLogger(__name__)
URL: str = "https://api.hypixel.net/v2/resources/skyblock/skills"


async def get_version() -> str:
    data = await http.get_json(URL)
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version:
        raise ValueError("The skills API did not return a version.")
    logger.debug("got version: %s", version)
    return version


def send(embed: disnake.Embed) -> list[Alert]:
    return utils.broadcast(constants.VERSION_TRACKER_CHANNELS, embed=embed)


class VersionTrackerCog(PollingCog):
    interval: float = 120

    def __init__(self, bot: SkypixelBot) -> None:
        super().__init__(bot)
        self.data: TrackerState[str] = TrackerState(bot.database, "version")
        if not self.data.get("version"):
            logger.warning("The saved SkyBlock version is empty.")

    def on_version_change(self, before: str, after: str) -> list[Alert]:
        embed = utils.add_footer(
            disnake.Embed(
                title="SkyBlock has updated!",
                description=f"`{before}` ➡ `{after}`",
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        return send(embed)

    async def poll(self) -> None:
        version = await get_version()
        if version != self.data.get("version"):
            logger.debug("version update: %s => %s", self.data.get("version"), version)
            alerts = (
                self.on_version_change(self.data["version"], version)
                if self.data.get("version")
                else []
            )
            await self.data.replace({**self.data, "version": version}, alerts)
