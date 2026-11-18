import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import disnake
from mcstatus import JavaServer

from skypixel import constants, utils
from skypixel.storage.database import Alert, TrackerState
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger = logging.getLogger(__name__)


async def get_motd() -> list[str]:
    logger.debug("getting mc.hypixel.net motd")
    status = await (await JavaServer.async_lookup("mc.hypixel.net")).async_status()
    return [line.strip() for line in status.description.split("\n")]


def send(embed: disnake.Embed, ping: bool = True) -> list[Alert]:
    return utils.broadcast(constants.MOTD_TRACKER_CHANNELS, embed=embed, ping=ping)


class MotdTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.data = TrackerState(bot.database, "motd")
        self._last_ping: datetime | None = None

    @property
    def last_ping(self) -> timedelta:
        return (
            datetime.now(UTC) - self._last_ping
            if self._last_ping is not None
            else timedelta.max
        )

    def on_motd_update(self, before: list[str], after: list[str]) -> list[Alert]:
        embed = utils.add_footer(
            disnake.Embed(
                title="Hypixel MOTD update!", color=constants.DEFAULT_EMBED_COLOR
            )
        )
        embed.add_field(name="Before", value=utils.ansi_block(before), inline=False)
        embed.add_field(name="After", value=utils.ansi_block(after), inline=False)
        return send(embed, ping=self.should_ping())

    def should_ping(self) -> bool:
        return self.last_ping.total_seconds() / 60 > 10

    async def poll(self):
        motd = await get_motd()
        if motd != self.data.get("motd"):
            logger.info("MOTD changed from %s to %s.", self.data.get("motd"), motd)
            alerts = []
            if self.data.get("motd"):
                alerts = self.on_motd_update(self.data.get("motd", []), motd)
            pinged = self.should_ping()
            await self.data.replace({**self.data, "motd": motd}, alerts)
            if alerts and pinged:
                self._last_ping = datetime.now(UTC)
