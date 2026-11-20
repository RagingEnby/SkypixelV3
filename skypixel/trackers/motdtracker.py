import asyncio
import logging
from datetime import UTC, datetime, timedelta

import disnake
from disnake.ext import commands
from dns.exception import DNSException
from mcstatus import JavaServer

from skypixel import constants, utils
from skypixel.storage.json import JsonWrapper
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)
LOOKUP_TIMEOUT = 10
STATUS_ATTEMPTS = 3


async def get_motd(*, attempts: int = STATUS_ATTEMPTS) -> list[str]:
    logger.debug("getting mc.hypixel.net motd")
    for attempt in range(attempts):
        try:
            server = await JavaServer.async_lookup(
                "mc.hypixel.net", timeout=LOOKUP_TIMEOUT
            )
            status = await server.async_status()
            return [line.strip() for line in status.description.split("\n")]
        except (OSError, DNSException):
            if attempt == attempts - 1:
                raise
            logger.warning(
                "Hypixel MOTD lookup failed. Retrying attempt %s.", attempt + 2
            )
            await asyncio.sleep(min(2**attempt, 5))
    raise RuntimeError("The MOTD lookup did not complete.")


async def send(bot: commands.InteractionBot, embed: disnake.Embed, ping: bool = True):
    await utils.broadcast(bot, constants.MOTD_TRACKER_CHANNELS, embed=embed, ping=ping)


class MotdTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: commands.InteractionBot):
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
        embed.add_field(
            name="Before", value="```" + "\n".join(before) + "```", inline=False
        )
        embed.add_field(
            name="After", value="```" + "\n".join(after) + "```", inline=False
        )
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
