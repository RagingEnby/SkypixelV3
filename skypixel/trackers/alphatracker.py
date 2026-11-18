import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import disnake
from mcstatus import JavaServer

from skypixel import alerts, constants, embed_utils, formatting
from skypixel.storage.json_store import JsonWrapper
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger = logging.getLogger(__name__)


def flatten_status(status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "MC Version": status["version"]["name"],
        "Version Protocol": status["version"]["protocol"],
        "Max Players": status["players"]["max"],
        "MOTD": status["description"],
    }


async def get_alpha_data() -> dict[str, Any]:
    status = await (await JavaServer.async_lookup("alpha.hypixel.net")).async_status()
    return flatten_status(status.raw)


async def send(bot: SkypixelBot, embed: disnake.Embed):
    await alerts.broadcast(bot, constants.ALPHA_TRACKER_CHANNELS, embed=embed)


class AlphaTrackerCog(PollingCog):
    interval = 240

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "alpha.json")

    async def on_status_update(self, before: dict[str, Any], after: dict[str, Any]):
        diff = [k for k, v in after.items() if v != before.get(k)]
        if not diff:
            return
        embed = embed_utils.add_footer(
            disnake.Embed(
                title="Alpha Status Updated!", color=constants.DEFAULT_EMBED_COLOR
            )
        )
        for key in diff:
            old, new = before.get(key), after[key]
            if isinstance(old, str) and isinstance(new, str) and "§" in old + new:
                value = (
                    f"Before:\n{formatting.ansi_block(old.split('\n'))}\n"
                    f"After:\n{formatting.ansi_block(new.split('\n'))}"
                )
            else:
                value = f"Before: `{old}`\nAfter: `{new}`"
            embed.add_field(name=key, value=value, inline=False)
        await send(self.bot, embed)

    async def poll(self):
        status = await get_alpha_data()
        if status != self.data.to_dict():
            if self.data.to_dict():
                logger.info("%s != %s", status, self.data.to_dict())
                await self.on_status_update(self.data.to_dict(), status)
            await self.data.replace(status)
