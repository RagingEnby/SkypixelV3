import logging
import time

import disnake
from disnake.ext import commands

from skypixel import utils
from skypixel.clients import hypixel
from skypixel.trackers import ranktracker
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)


class StatusUpdaterCog(PollingCog):
    interval = 20
    rank_statuses = (
        "staff",
        "youtube",
        "pig_plus_plus_plus",
        "innit",
        "events",
        "mojang",
        "mcp",
    )
    item_count_statuses = (
        "CAKE_SOUL",
        "DUECES_BUILDER_CLAY",
        "POTATO_BASKET",
        "ANCIENT_ELEVATOR",
        "WIZARD_PORTAL_MEMENTO",
        "RACING_HELMET",
        "DCTR_SPACE_HELM",
    )

    # The item counts change slowly, so count each item twice an hour at most.
    count_ttl = 30 * 60

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.index = 0
        self._counts: dict[str, tuple[float, int]] = {}

    async def change_presence(self, text: str):
        logger.debug("Changing status to '%s'", text)
        return await self.bot.change_presence(
            status=disnake.Status.online, activity=disnake.CustomActivity(name=text)
        )

    async def _rank_status(self, rank: str):
        rank_lists = await ranktracker.get_rank_lists()
        return await self.change_presence(
            f"Tracking {utils.commaize(len(rank_lists.get(rank, [])))} "
            f"{ranktracker.format_rank(rank)} players"
        )

    async def _item_count(self, item_id: str) -> int:
        cached = self._counts.get(item_id)
        if cached and time.monotonic() - cached[0] < self.count_ttl:
            return cached[1]
        itemdb_cog = self.bot.get_cog("ItemDBCog")
        if not itemdb_cog:
            return 0
        count = await itemdb_cog.item_db.count_documents({"itemId": item_id})
        self._counts[item_id] = (time.monotonic(), count)
        return count

    async def _item_count_status(self, item_id: str):
        try:
            name = hypixel.get_name(item_id)
        except (KeyError, ValueError):  # fmt: skip
            name = item_id
        count = await self._item_count(item_id)
        return await self.change_presence(
            f"Tracking {utils.commaize(count)} {name} items"
        )

    async def change_status(self):
        if self.index == 0:
            await self.change_presence(f"In {len(self.bot.guilds)} servers")
        elif self.index == 1:
            await self.change_presence("Made by @ragingenby")
        elif self.index < 2 + len(self.rank_statuses):
            await self._rank_status(self.rank_statuses[self.index - 2])
        else:
            await self._item_count_status(
                self.item_count_statuses[self.index - 2 - len(self.rank_statuses)]
            )

    async def poll(self):
        try:
            await self.change_status()
        finally:
            self.index = (self.index + 1) % (
                2 + len(self.rank_statuses) + len(self.item_count_statuses)
            )
