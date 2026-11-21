import logging

import disnake
from curl_cffi.requests.exceptions import HTTPError, Timeout
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

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.index = 0

    async def change_presence(self, activity_type: disnake.ActivityType, name: str):
        logger.debug("Changing status to %s '%s'", activity_type, name)
        return await self.bot.change_presence(
            status=disnake.Status.online,
            activity=disnake.Activity(type=activity_type, name=name),
        )

    async def _rank_status(self, rank: str):
        fallback_error: HTTPError | Timeout | None = None
        try:
            rank_lists = await ranktracker.get_rank_lists()
        except (HTTPError, Timeout) as error:
            if isinstance(error, HTTPError) and (
                error.response is None
                or error.response.status_code not in {502, 503, 504}
            ):
                raise
            rank_counts = await ranktracker.get_rank_counts()
            count = rank_counts[rank]
            fallback_error = error
        else:
            count = len(rank_lists.get(rank, []))
        await self.change_presence(
            activity_type=disnake.ActivityType.listening,
            name=f"{utils.commaize(count)} {ranktracker.format_rank(rank)} ranks",
        )
        if fallback_error is not None:
            logger.warning(
                "Updated the rank status using rank counts (%s).", fallback_error
            )

    async def _item_count_status(self, item_id: str):
        try:
            name = hypixel.get_name(item_id)
        except (KeyError, ValueError):  # fmt: skip
            name = item_id
        itemdb_cog = self.bot.get_cog("ItemDBCog")
        if itemdb_cog:
            count = await itemdb_cog.item_db.count_documents({"itemId": item_id})
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
                    name=f"{len(self.bot.guilds)} servers",
                )
            )
        elif self.index == 1:
            await self.change_presence(
                activity_type=disnake.ActivityType.playing,
                name="Owner: @ragingenby",
            )
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
