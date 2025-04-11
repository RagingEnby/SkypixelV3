import asyncio
import traceback

import disnake
from disnake.ext import commands
from mcstatus import JavaServer

import constants
from modules import datamanager
from modules import utils


async def get_motd() -> list[str]:
    status = await JavaServer.lookup("mc.hypixel.net").async_status()
    return [l.strip() for l in status.description.split("\n")]


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.MOTD_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class MotdTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/motd.json")

    async def on_motd_update(self, before: list[str], after: list[str]):
        embed = utils.add_footer(disnake.Embed(
            title="Hypixel MOTD update!",
            color=constants.DEFAULT_EMBED_COLOR
        ))
        embed.add_field(
            name="Before",
            value='```' + '\n'.join(before) + '```',
            inline=False
        )
        embed.add_field(
            name="After",
            value='```' + '\n'.join(after) + '```',
            inline=False
        )
        await send(embed)

    async def main(self):
        while True:
            try:
                motd = await get_motd()
                if motd != self.data.get('motd'):
                    if self.data.get('motd'):
                        await self.on_motd_update(self.data.get('motd', []), motd)
                    self.data['motd'] = motd
                    await self.data.save()
            except Exception:
                print("motd tracker error:", traceback.format_exc())
            finally:
                await asyncio.sleep(240)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
