from skypixel.trackers.base import PollingCog

import asyncio
import logging
from typing import Callable, Coroutine

import disnake
from disnake.ext import commands

from skypixel.trackers import ranktracker
from skypixel.clients import hypixel
from skypixel import discord as utils

logger = logging.getLogger(__name__)


class StatusUpdaterCog(PollingCog):
    interval = 20

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.index = 0
        self.rank_statuses: list[Callable[[], Coroutine]] = [
            lambda rank=rank: self._rank_status(rank)
            for rank in (
                "staff",
                "youtube",
                "pig_plus_plus_plus",
                "innit",
                "events",
                "mojang",
                "mcp",
            )
        ]
        self.item_count_statuses: list[Callable[[], Coroutine]] = [
            lambda item_id=item_id: self._item_count_status(item_id)
            for item_id in (
                "CAKE_SOUL",
                "DUECES_BUILDER_CLAY",
                "POTATO_BASKET",
                "ANCIENT_ELEVATOR",
                "WIZARD_PORTAL_MEMENTO",
                "RACING_HELMET",
                "DCTR_SPACE_HELM",
            )
        ]

    async def change_presence(self, activity_type: disnake.ActivityType, name: str):
        logger.debug(f"Changing status to {activity_type} '{name}'")
        return await self.bot.change_presence(
            status=disnake.Status.online,  # type: ignore[assignment]
            activity=disnake.Activity(type=activity_type, name=name),
        )

    async def _rank_status(self, rank: str):
        rank_counts = await ranktracker.get_rank_counts()
        if rank not in rank_counts:
            raise KeyError(rank)
        return await self.change_presence(
            activity_type=disnake.ActivityType.listening,  # type: ignore[assignment]
            name=(
                f"{utils.commaize(rank_counts[rank])} "
                f"{ranktracker.format_rank(rank)} ranks"
            ),
        )

    async def _item_count_status(self, item_id: str):
        try:
            name = hypixel.get_name(item_id)
        except KeyError:
            name = item_id
        itemdb_cog = self.bot.get_cog("ItemDBCog")
        if itemdb_cog:
            count = await itemdb_cog.item_db.count_documents({"itemId": item_id})  # type: ignore[attr-defined]
        else:
            count = 0
        return await self.change_presence(
            activity_type=disnake.ActivityType.watching,  # type: ignore[assignment]
            name=f"{utils.commaize(count)} {name} items",
        )

    async def change_status(self):
        if self.index == 0:
            await self.bot.change_presence(
                activity=disnake.Activity(
                    type=disnake.ActivityType.listening,
                    name=f"{len(self.bot.guilds)} servers",
                )
            )
            return None
        elif self.index == 1:
            await self.change_presence(
                activity_type=disnake.ActivityType.playing,  # type: ignore[assignment]
                name="Owner: @ragingenby",
            )
            return None
        elif 2 <= self.index <= 8:
            await self.rank_statuses[self.index - 2]()
            return None
        elif 9 <= self.index <= 15:
            await self.item_count_statuses[self.index - 9]()
            return None
        else:
            self.index = 0
            return await self.change_status()

    async def poll(self):
        await self.change_status()
        self.index += 1
