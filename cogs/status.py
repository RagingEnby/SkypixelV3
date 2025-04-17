import asyncio
import logging
import traceback
from typing import Coroutine

import disnake
from disnake.ext import commands

from cogs import ranktracker
from modules import hypixel, utils

logger = logging.getLogger(__name__)


class StatusUpdaterCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.index = 0
        self.rank_statuses: list[Coroutine] = [
            self._rank_status('gm'),
            self._rank_status('admin'),
            self._rank_status('youtube'),
            self._rank_status('owner'),
            self._rank_status('pig_plus_plus_plus'),
            self._rank_status('innit'),
            self._rank_status('events'),
            self._rank_status('mojang'),
            self._rank_status('mcp')
        ]
        self.item_count_statuses: list[Coroutine] = [
            self._item_count_status('CAKE_SOUL'),
            self._item_count_status('DUECES_BUILDER_CLAY'),
            self._item_count_status('POTATO_BASKET'),
            self._item_count_status('ANCIENT_ELEVATOR'),
            self._item_count_status('WIZARD_PORTAL_MEMENTO'),
            self._item_count_status('RACING_HELMET'),
            self._item_count_status('DCTR_SPACE_HELM')
        ]

    async def change_presence(self, activity_type: disnake.ActivityType, name: str):
        logger.debug(f"Changing status to {activity_type} '{name}'")
        return await self.bot.change_presence(
            status=disnake.Status.online(),
            activity=disnake.Activity(
                type=activity_type,
                name=name
            )
        )

    async def _rank_status(self, rank: str):
        rank_counts = await ranktracker.get_rank_counts()
        if rank not in rank_counts:
            raise KeyError(rank)
        return await self.change_presence(
            activity_type=disnake.ActivityType.listening,
            name=f"{utils.commaize(rank_counts[rank])} {ranktracker.format_rank(rank)} ranks",
        )

    async def _item_count_status(self, item_id: str):
        try:
            name = hypixel.get_name(item_id)
        except KeyError:
            name = item_id
        itemdb_cog = self.bot.get_cog('ItemDBCog')
        if itemdb_cog:
            count = await itemdb_cog.item_db.count_documents({"itemId": item_id}) # type: ignore[attr-defined]
        else:
            count = 0
        return await self.change_presence(
            activity_type=disnake.ActivityType.watching,
            name=f"{utils.commaize(count)} {name} items",
        )

    async def change_status(self):
        if self.index == 0:
            await self.bot.change_presence(
                activity=disnake.Activity(
                    type=disnake.ActivityType.listening,
                    name=f"{len(self.bot.guilds)} servers"
                )
            )
        elif self.index == 1:
            await self.change_presence(
                activity_type=disnake.ActivityType.playing,
                name="Owner: @ragingenby"
            )
        elif 2 <= self.index <= 10:
            await self.rank_statuses[self.index - 2]
        elif 11 <= self.index <= 16:
            await self.item_count_statuses[self.index - 11]
        else:
            self.index = 0
            return await self.change_status()



    async def main(self):
        while True:
            try:
                await self.change_status()
                self.index += 1
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(20)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
