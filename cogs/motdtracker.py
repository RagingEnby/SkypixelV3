import asyncio
import logging
import traceback
from datetime import datetime, timedelta

import disnake
from disnake.ext import commands
from mcstatus import JavaServer

import constants
from modules import datamanager
from modules import utils

logger = logging.getLogger(__name__)


async def get_motd() -> list[str]:
    logger.debug("getting mc.hypixel.net motd")
    status = await JavaServer.lookup("mc.hypixel.net").async_status()
    return [l.strip() for l in status.description.split("\n")]


async def send(embed: disnake.Embed, ping: bool = True):
    tasks = [
        utils.send_to_channel(channel_id, content if ping else None, embed=embed)
        for channel_id, content in constants.MOTD_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class MotdTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/motd.json")
        self._last_ping: datetime | None = None

    @property
    def last_ping(self) -> timedelta:
        return (
            datetime.now() - self._last_ping
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
        # only ping every 10 minutes (don't want to repeat tge 10/4/25 incident)
        should_ping = self.last_ping.total_seconds() / 60 > 10
        await send(embed, ping=should_ping)
        self._last_ping = datetime.now()

    async def main(self):
        while True:
            try:
                motd = await get_motd()
                if motd != self.data.get("motd"):
                    logger.info("motd update:", self.data.get("motd"), "=>", motd)
                    if self.data.get("motd"):
                        await self.on_motd_update(self.data.get("motd", []), motd)
                    self.data["motd"] = motd
                    await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(240)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
