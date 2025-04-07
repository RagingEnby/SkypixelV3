from typing import Any
import disnake
from disnake.ext import commands
from mcstatus import JavaServer
from mcstatus.status_response import JavaStatusResponse, RawJavaResponse
import traceback
import asyncio

from modules import datamanager
from modules import utils

import constants


def flatten_status(status: RawJavaResponse) -> dict[str, Any]:
    return {
        "MC Version": status['version']['name'],
        "Version Protocol": status['version']['protocol'],
        "Max Players": status['players']['max'],
        "Online Players": status['players']['online'],
        "MOTD": status['description'],
    }


async def get_alpha_data() -> dict[str, Any]:
    status = await JavaServer.lookup("alpha.hypixel.net").async_status()
    return flatten_status(status.raw)


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.ALPHA_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class AlphaTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/alpha.json")

    async def on_status_update(self, before: dict[str, Any], after: dict[str, Any]):
        diff = [
            k for k, v in after.items()
            if v != before.get(k)
        ]
        if not diff:
            return
        embed = utils.add_footer(disnake.Embed(
            title="Alpha Status Updated!",
            color=constants.DEFAULT_EMBED_COLOR
        ))
        for key in diff:
            embed.add_field(
                name=key,
                value=f"**Before:** `{before.get(key)}`\n**After:** `{after[key]}`",
                inline=False
            )
        await send(embed)

    async def main(self):
        while True:
            try:
                status = await get_alpha_data()
                if status != self.data.to_dict():
                    print(status, '!=', self.data.to_dict())
                    await self.on_status_update(self.data.to_dict(), status)
                    self.data.update(status)
                    await self.data.save()
                await asyncio.sleep(120)
            except Exception:
                print("alpha tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())
