import logging
from typing import Any

import disnake
from disnake.ext import commands
from mcstatus import JavaServer
from mcstatus.responses._raw import RawJavaResponse

from skypixel import constants
from skypixel import discord as utils
from skypixel.storage import json as datamanager
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)


def flatten_status(status: RawJavaResponse) -> dict[str, Any]:
    return {
        "MC Version": status["version"]["name"],
        "Version Protocol": status["version"]["protocol"],
        "Max Players": status["players"]["max"],
        "MOTD": status["description"],
    }


async def get_alpha_data() -> dict[str, Any]:
    status = await (await JavaServer.async_lookup("alpha.hypixel.net")).async_status()
    return flatten_status(status.raw)


async def send(embed: disnake.Embed):
    await utils.broadcast(constants.ALPHA_TRACKER_CHANNELS, embed=embed)


class AlphaTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = datamanager.JsonWrapper(constants.STORAGE_DIR / "alpha.json")

    @staticmethod
    async def on_status_update(before: dict[str, Any], after: dict[str, Any]):
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
        await send(embed)

    async def poll(self):
        status = await get_alpha_data()
        if status != self.data.to_dict():
            if self.data.to_dict():
                logger.info(f"{status} != {self.data.to_dict()}")
                await self.on_status_update(self.data.to_dict(), status)
            self.data.data = status
            await self.data.save()
