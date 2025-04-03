import disnake
from disnake.ext import commands
import asyncio

from modules import mongodb

import constants


class ItemSearchCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.item_db = mongodb.Collection("SkyBlock", "items")
        self.bot = bot

    @commands.slash_command(
        name="itemdb",
        description="Commands that use the RagingEnby item database"
    )
    async def itemdb_cmd(self, inter: disnake.AppCmdInter):
        await inter.response.defer()

    @commands.Cog.listener()
    async def on_ready(self):
        def signal_handler(sig: int, _):
            asyncio.create_task(self.item_db.close())

