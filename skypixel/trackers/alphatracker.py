import asyncio
import logging
from typing import Any

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


def flatten_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "MC Version": status["version"]["name"],
        "Version Protocol": status["version"]["protocol"],
        "Max Players": status["players"]["max"],
        "MOTD": status["description"],
    }


async def get_alpha_data(*, attempts: int = STATUS_ATTEMPTS) -> dict[str, Any]:
    for attempt in range(attempts):
        try:
            server = await JavaServer.async_lookup(
                "alpha.hypixel.net", timeout=LOOKUP_TIMEOUT
            )
            status = await server.async_status()
            return flatten_status(status.raw)
        except (OSError, DNSException):
            if attempt == attempts - 1:
                raise
            logger.warning(
                "Hypixel alpha lookup failed. Retrying attempt %s.", attempt + 2
            )
            await asyncio.sleep(min(2**attempt, 5))
    raise RuntimeError("The alpha status lookup did not complete.")


async def send(bot: commands.InteractionBot, embed: disnake.Embed):
    await utils.broadcast(bot, constants.ALPHA_TRACKER_CHANNELS, embed=embed)


class AlphaTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "alpha.json")

    async def on_status_update(self, before: dict[str, Any], after: dict[str, Any]):
        diff = [k for k, v in after.items() if v != before.get(k)]
        if not diff:
            return
        embed = utils.add_footer(
            disnake.Embed(
                title="Alpha Status Updated!", color=constants.DEFAULT_EMBED_COLOR
            )
        )
        for key in diff:
            embed.add_field(
                name=key,
                value=f"Before: `{before.get(key)}`\nAfter: `{after[key]}`",
                inline=False,
            )
        await send(self.bot, embed)

    async def poll(self):
        status = await get_alpha_data()
        if status != self.data.to_dict():
            if self.data.to_dict():
                logger.info("%s != %s", status, self.data.to_dict())
                await self.on_status_update(self.data.to_dict(), status)
            await self.data.replace(status)
