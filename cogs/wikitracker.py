import disnake
from disnake.ext import commands
import asyncio
import traceback

from modules import asyncreqs
from modules import datamanager
from modules import utils

import constants


URL: str = "https://wiki.hypixel.net/api.php"
PARAMS: dict[str, str] = {
    "action": "query",
    "format": "json",
    "uselang": "user",
    "variant": "",
    "errorformat": "bc",
    "list": "recentchanges",
    "rcnamespace": "*",
    "rcprop": '|'.join([
        "comment", "flags", "ids", "loginfo", "parsedcomment", "redirect",
        "sha1", "sizes", "tags", "timestamp", "title", "user", "userid"
    ]),
    "rctype": '|'.join(["categorize", "edit", "external", "log", "new"])
}


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.WIKI_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class WikiTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/wikiedits.json")

    async def on_version_change(self, before: str, after: str):
        embed = utils.add_footer(disnake.Embed(
            color=constants.DEFAULT_EMBED_COLOR
        ))
        await send(embed)

    async def main(self):
        while True:
            try:
                await asyncio.sleep(120)
            except Exception:
                print("version tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())
