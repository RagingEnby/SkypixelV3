import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import disnake
from mcstatus import JavaServer

from skypixel import constants, utils
from skypixel.storage.json_store import JsonWrapper
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger = logging.getLogger(__name__)


async def get_motd() -> list[str]:
    logger.debug("getting mc.hypixel.net motd")
    status = await (await JavaServer.async_lookup("mc.hypixel.net")).async_status()
    return [line.strip() for line in status.description.split("\n")]


async def send(bot: SkypixelBot, embed: disnake.Embed, ping: bool = True):
    await utils.broadcast(bot, constants.MOTD_TRACKER_CHANNELS, embed=embed, ping=ping)


class MotdTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "motd.json")
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
        embed.add_field(name="Before", value=utils.ansi_block(before), inline=False)
        embed.add_field(name="After", value=utils.ansi_block(after), inline=False)
        should_ping = self.last_ping.total_seconds() / 60 > 10
        await send(self.bot, embed, ping=should_ping)
        if should_ping:
            self._last_ping = datetime.now(UTC)

    async def poll(self):
        motd = await get_motd()
        if motd != self.data.get("motd"):
            logger.info("MOTD changed from %s to %s.", self.data.get("motd"), motd)
            if self.data.get("motd"):
                await self.on_motd_update(self.data.get("motd", []), motd)
            await self.data.replace({**self.data, "motd": motd})
