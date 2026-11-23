import logging
from typing import Any

import disnake
from disnake.ext import commands
from mcstatus.responses import JavaStatusResponse

from skypixel import constants, utils
from skypixel.clients import minecraft
from skypixel.storage.json import JsonWrapper
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)


def flatten_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "MC Version": status["version"]["name"],
        "Version Protocol": status["version"]["protocol"],
        "Max Players": status["players"]["max"],
        "MOTD": status["description"],
    }


async def get_alpha_data() -> dict[str, Any]:
    status: JavaStatusResponse = await minecraft.get_status("alpha.hypixel.net")
    return flatten_status(status.raw)


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
