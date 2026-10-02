import logging
from datetime import UTC, datetime, timedelta

import disnake
from disnake.ext import commands
from mcstatus import JavaServer

from skypixel import constants, utils
from skypixel.settings import settings
from skypixel.storage.json import JsonWrapper
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)


async def get_motd() -> list[str]:
    logger.debug("getting mc.hypixel.net motd")
    status = await (await JavaServer.async_lookup("mc.hypixel.net")).async_status()
    return [line.strip() for line in status.description.split("\n")]


async def send(embed: disnake.Embed, ping: bool = True):
    await utils.broadcast(constants.MOTD_TRACKER_CHANNELS, embed=embed, ping=ping)


class MotdTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(settings.storage_dir / "motd.json")
        self._last_ping: datetime | None = None

    @property
    def last_ping(self) -> timedelta:
        return (
            datetime.now(UTC) - self._last_ping
            if self._last_ping is not None
            else timedelta.max
        )

    async def on_motd_update(self, before: list[str], after: list[str]):
        embed = utils.add_footer(
            disnake.Embed(
                title="Hypixel MOTD update!", color=constants.DEFAULT_EMBED_COLOR
            )
        )
        embed.add_field(
            name="Before", value="```" + "\n".join(before) + "```", inline=False
        )
        embed.add_field(
            name="After", value="```" + "\n".join(after) + "```", inline=False
        )
        # Wait at least ten minutes between role pings.
        should_ping = self.last_ping.total_seconds() / 60 > 10
        await send(embed, ping=should_ping)
        if should_ping:
            self._last_ping = datetime.now(UTC)

    async def poll(self):
        motd = await get_motd()
        if motd != self.data.get("motd"):
            logger.info("MOTD changed from %s to %s.", self.data.get("motd"), motd)
            if self.data.get("motd"):
                await self.on_motd_update(self.data.get("motd", []), motd)
            self.data["motd"] = motd
            await self.data.save()
