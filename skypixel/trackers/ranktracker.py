import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

import disnake
from curl_cffi.requests.exceptions import HTTPError, RequestException
from disnake.ext import commands

from skypixel import constants, subscriptions, utils
from skypixel.clients import http, mojang
from skypixel.commands.rank_views import RankListView
from skypixel.domain.types import SpecialRank
from skypixel.storage.json_store import JsonWrapper
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger = logging.getLogger(__name__)

URL: str = "https://api.ragingenby.dev/hypixel/ranks"
RANK_URL: str = URL + "/{}"
COUNTS_URL: str = RANK_URL.format("counts")
RANKNAME_URL: str = "https://api.ragingenby.dev/hypixel/rank/{}"
RANK_LIST_CACHE_TTL_SECONDS = 180
RANK_LIST_CACHE: dict[str, list[dict[str, str]]] | None = None
RANK_LIST_CACHE_TIME = 0.0
RANK_LIST_CACHE_LOCK = asyncio.Lock()
RANK_LIST_GENERATION = 0
POI_UUIDS: set[str] = set()
WATCH_LIST_LIMIT = 25


def watched_rankname(entry: Any) -> str | None:
    """Return the rank name stored for a watched player.

    Entries saved before the watchlist recorded who added a player are the
    rank name itself.
    """
    return entry.get("rankname") if isinstance(entry, dict) else entry


def invalidate_rank_lists() -> None:
    """Refetch the player lists on the next read, even during a fetch."""
    global RANK_LIST_CACHE, RANK_LIST_GENERATION
    RANK_LIST_CACHE = None
    RANK_LIST_GENERATION += 1


async def get_rankname(identifier: str) -> str:
    if not mojang.is_valid_identifier(identifier):
        raise mojang.PlayerNotFound(identifier)
    response = await http.get(RANKNAME_URL.format(identifier))
    if response.status_code == 404:
        raise mojang.PlayerNotFound(identifier)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("rankname"), str):
        raise ValueError("The rank API did not return a rank name.")
    return data["rankname"]


async def get_rank_counts() -> dict[str, int]:
    data: dict[str, int] = await http.get_json(COUNTS_URL)
    logger.debug("rank counts: %s", data)
    return dict(sorted(data.items(), key=lambda item: item[1], reverse=True))


async def get_rank_list(rank: SpecialRank) -> list[dict[str, str]]:
    return await http.get_json(RANK_URL.format(rank))


async def edit_stat_channels(
    bot: SkypixelBot, rank_data: dict[str, list[dict[str, str]]]
):
    rank_data = rank_data.copy()
    rank_data["special"] = [
        player
        for key, players in rank_data.items()
        if key not in subscriptions.current().rank
        for player in players
    ]
    tasks = []
    for rank in subscriptions.current().rank:
        players = rank_data.get(rank, [])
        channels = subscriptions.current().rank[rank]
        for channel_id in channels:
            channel = bot.get_channel(channel_id)
            name = f"{rank}-{len(players)}"
            if not isinstance(channel, disnake.TextChannel):
                logger.error(
                    "channel %s is not a text channel: %s", channel_id, type(channel)
                )
                continue
            if channel.name.startswith(f"{rank}-") and channel.name != name:
                logger.info("renaming #%s (%s) to %s", channel.name, channel.id, name)
                tasks.append(channel.edit(name=name))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Cannot rename a rank channel.", exc_info=result)


async def get_rank_lists() -> dict[str, list[dict[str, str]]]:
    global RANK_LIST_CACHE, RANK_LIST_CACHE_TIME
    async with RANK_LIST_CACHE_LOCK:
        if (
            RANK_LIST_CACHE is None
            or time.monotonic() - RANK_LIST_CACHE_TIME >= RANK_LIST_CACHE_TTL_SECONDS
        ):
            generation = RANK_LIST_GENERATION
            data = await http.get_json(URL)
            if (
                not isinstance(data, dict)
                or not data
                or any(
                    not isinstance(players, list)
                    or any(
                        not isinstance(player, dict)
                        or not isinstance(player.get("id"), str)
                        or not isinstance(player.get("name"), str)
                        for player in players
                    )
                    for players in data.values()
                )
            ):
                raise ValueError("The rank API did not return player lists.")
            RANK_LIST_CACHE = data
            RANK_LIST_CACHE_TIME = (
                time.monotonic()
                if generation == RANK_LIST_GENERATION
                else float("-inf")
            )
        data = {
            rank: [player.copy() for player in players]
            for rank, players in RANK_LIST_CACHE.items()
        }
        POI_UUIDS.clear()
        POI_UUIDS.update(
            player["id"] for players in data.values() for player in players
        )
    return data


async def get_player_ranks() -> dict[str, dict[str, str | SpecialRank]]:
    data = await get_rank_lists()
    return {
        player["id"]: {"rank": rank, "name": player["name"]}
        for rank, players in data.items()
        for player in players
    }


async def send(
    bot: SkypixelBot,
    rank: Literal["special"] | SpecialRank,
    embed: disnake.Embed,
    ping: bool = True,
):
    if rank not in subscriptions.current().rank:
        rank = "special"
    await utils.broadcast(
        bot, subscriptions.current().rank[rank], embed=embed, ping=ping
    )


def shrunken_ranks(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> list[str]:
    """Return ranks with at least five players that lost more than half."""
    old_counts = Counter(player["rank"] for player in before.values())
    new_counts = Counter(player["rank"] for player in after.values())
    return sorted(
        rank
        for rank, count in old_counts.items()
        if count >= 5 and new_counts[rank] < count / 2
    )


def format_rank(rank: str) -> str:
    return "[" + rank.replace("_plus", "+").replace("_", " ").upper() + "]"


def make_embed(uuid: str, name: str, rank: SpecialRank, title: str) -> disnake.Embed:
    embed = utils.add_footer(
        disnake.Embed(
            title=title,
            color=constants.RANK_COLORS.get(rank, constants.DEFAULT_EMBED_COLOR),
        )
    )
    return embed.set_author(
        name=f"{format_rank(rank)} {name}",
        icon_url=constants.MC_HEAD_IMAGE.format(uuid),
    )


class RankTrackerCog(PollingCog):
    interval = 240
    confirm_polls = 3

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "ranks.json")
        self.watch_list = JsonWrapper(bot.settings.storage_dir / "rankwatchlist.json")
        if not self.data.to_dict():
            logger.warning("ranks.json is empty")
        self.known_changes: set[tuple[str, ...]] = set()
        self.shrunken_polls = 0
        self.shrunken_changes: frozenset[tuple[str, str, str | None]] | None = None

    async def update_stat_channels(self, player_ranks: dict[str, dict]) -> None:
        ranks: dict[str, list[dict[str, str]]] = {}
        for uuid, player in player_ranks.items():
            ranks.setdefault(player["rank"], []).append(
                {"id": uuid, "name": player["name"]}
            )
        await edit_stat_channels(self.bot, ranks)

    async def notify_change(
        self, key: tuple[str, ...], notify: Callable[..., Awaitable[None]], *args: str
    ) -> None:
        if key not in self.known_changes:
            await notify(*args)
            self.known_changes.add(key)

    async def on_rank_add(self, uuid: str, name: str, rank: SpecialRank):
        embed = make_embed(
            uuid,
            name,
            rank,
            f"{utils.esc_mrkdwn(name)} now has {format_rank(rank)} rank!",
        )
        logger.info("rank tracker alert: %s", embed.title)
        await send(self.bot, rank, embed)

    async def on_rank_change(
        self, uuid: str, name: str, before: SpecialRank, after: SpecialRank
    ):
        """Send one alert to every channel that follows the old or the new rank."""
        embed = make_embed(
            uuid,
            name,
            after,
            f"{utils.esc_mrkdwn(name)} went from {format_rank(before)} "
            f"to {format_rank(after)} rank!",
        )
        logger.info("rank tracker alert: %s", embed.title)
        channels: dict[int, str] = {}
        for rank in (before, after):
            key = rank if rank in subscriptions.current().rank else "special"
            channels.update(subscriptions.current().rank[key])
        await utils.broadcast(self.bot, channels, embed=embed)

    async def on_rank_remove(self, uuid: str, name: str, rank: SpecialRank):
        embed = make_embed(
            uuid,
            name,
            rank,
            f"{utils.esc_mrkdwn(name)} has lost {format_rank(rank)} rank",
        )
        logger.info("rank tracker alert: %s", embed.title)
        await send(self.bot, rank, embed)

    async def on_name_change(
        self, uuid: str, before: str, after: str, rank: SpecialRank
    ):
        embed = make_embed(
            uuid,
            after,
            rank,
            f"{utils.esc_mrkdwn(before)} changed their IGN to {utils.esc_mrkdwn(after)}",
        )
        logger.info("rank tracker alert: %s", embed.title)
        await send(self.bot, rank, embed, ping=False)

    async def do_watchlist(self):
        for uuid, entry in list(self.watch_list.items()):
            last_rankname = watched_rankname(entry)
            try:
                rankname = await get_rankname(uuid)
                logger.info("rank watchlist: %s -> %s", last_rankname, rankname)
                if last_rankname is None:
                    await self.watch_list.set_and_save(
                        uuid,
                        {**entry, "rankname": rankname}
                        if isinstance(entry, dict)
                        else rankname,
                    )
                    continue
                if rankname != last_rankname:
                    invalidate_rank_lists()
                    await self.watch_list.remove_and_save(uuid)
            except HTTPError as error:
                if error.response is not None and error.response.status_code == 429:
                    logger.warning(
                        "The rank API rate limit stopped the watchlist scan."
                    )
                    return
                logger.exception("Cannot update player %s in the rank watchlist.", uuid)
            except (RequestException, KeyError, ValueError):  # fmt: skip
                logger.exception("Cannot update player %s in the rank watchlist.", uuid)

    @commands.slash_command(
        name="ranks",
        description="Various utilities relating to Special Hypixel ranks!",
        install_types=disnake.ApplicationInstallTypes.all(),
        contexts=disnake.InteractionContextTypes.all(),
    )
    async def ranks(self, inter: disnake.AppCmdInter):
        await inter.response.defer()

    @ranks.sub_command(
        name="update", description="Update a player's rank in my database"
    )
    async def update(self, inter: disnake.AppCmdInter, player: str):
        """
        Parameters
        ----------
        player: A Minecraft username or UUID
        """
        try:
            rankname = await get_rankname(player)
            invalidate_rank_lists()
        except mojang.PlayerNotFound:
            if not mojang.is_valid_identifier(player):
                return await utils.send_error(
                    inter, "Invalid player!", "Enter a Minecraft username or UUID."
                )
            return await utils.send_error(
                inter,
                "Player not found!",
                f"No player named [{player}](https://namemc.com/search?q={player.lower()}) was found. Please check your spelling and try again.",
            )
        unformatted = utils.remove_color_codes(rankname)
        embed = utils.add_footer(
            disnake.Embed(
                description=f"Successfully updated `{unformatted}`",
                color=constants.COLOR_CODES["a"],
            )
        )
        embed.set_image(url=utils.to_mc_text(rankname))
        return await inter.send(embed=embed)

    @ranks.sub_command(
        name="watch", description="Check a player for rank changes more often"
    )
    async def watch(self, inter: disnake.AppCmdInter, player: str):
        """
        Parameters
        ----------
        player: A Minecraft username or UUID
        """
        try:
            player_obj = await mojang.get(player)
        except mojang.PlayerNotFound:
            return await utils.send_error(
                inter,
                "Player not found!",
                f"I couldn't find the player `{player.replace('`', '')}`!",
            )
        if len(self.watch_list) >= WATCH_LIST_LIMIT:
            return await utils.send_error(
                inter,
                "Watchlist Full!",
                f"The watchlist can hold {WATCH_LIST_LIMIT} players. "
                "Wait for a watched player's rank to change, "
                "or remove one with /ranks unwatch.",
            )
        if player_obj.id in self.watch_list:
            return await utils.send_error(
                inter,
                "Already Watching!",
                f"`{player_obj.name}` is already in the watchlist.",
            )
        await self.watch_list.set_and_save(
            player_obj.id,
            {"rankname": None, "name": player_obj.name, "added_by": inter.author.id},
        )
        await inter.send(
            embed=utils.add_footer(
                disnake.Embed(
                    title="Added To Watchlist",
                    description=f"Now tracking `{player_obj.name}` for rank changes!",
                    color=constants.DEFAULT_EMBED_COLOR,
                )
            )
        )

    @ranks.sub_command(
        name="unwatch", description="Remove a player you added from the watchlist"
    )
    async def unwatch(self, inter: disnake.AppCmdInter, player: str):
        """
        Parameters
        ----------
        player: A Minecraft username or UUID
        """
        try:
            player_obj = await mojang.get(player)
        except mojang.PlayerNotFound:
            return await utils.send_error(
                inter,
                "Player not found!",
                f"I couldn't find the player `{player.replace('`', '')}`!",
            )
        if player_obj.id not in self.watch_list:
            return await utils.send_error(
                inter, "Not Watching!", f"`{player_obj.name}` is not in the watchlist."
            )
        entry = self.watch_list[player_obj.id]
        added_by = entry.get("added_by") if isinstance(entry, dict) else None
        if added_by != inter.author.id and not await self.bot.is_owner(inter.author):
            return await utils.send_error(
                inter,
                "Not Your Player!",
                "Only the user who added this player can remove them.",
            )
        await self.watch_list.remove_and_save(player_obj.id)
        await inter.send(
            embed=utils.add_footer(
                disnake.Embed(
                    title="Removed From Watchlist",
                    description=f"No longer tracking `{player_obj.name}`.",
                    color=constants.DEFAULT_EMBED_COLOR,
                )
            )
        )

    @ranks.sub_command(name="watchlist", description="Show the watched players")
    async def show_watchlist(self, inter: disnake.AppCmdInter):
        lines = []
        for uuid, entry in self.watch_list.items():
            if isinstance(entry, dict):
                lines.append(
                    f"`{entry.get('name', uuid)}` added by <@{entry.get('added_by')}>"
                )
            else:
                lines.append(f"`{uuid}`")
        await inter.send(
            embed=utils.add_footer(
                disnake.Embed(
                    title=f"Watchlist ({len(lines)}/{WATCH_LIST_LIMIT})",
                    description="\n".join(lines) or "Nobody is being watched.",
                    color=constants.DEFAULT_EMBED_COLOR,
                )
            )
        )

    @ranks.sub_command(
        name="counts", description="Get the number of players with each rank"
    )
    async def counts(self, inter: disnake.AppCmdInter):
        counts = await get_rank_counts()
        counts.pop("normal", None)
        embed = utils.add_footer(
            disnake.Embed(
                title="Rank Counts",
                description="\n".join(
                    [
                        f"**{format_rank(rank)}:** `{utils.commaize(count)}`"
                        for rank, count in counts.items()
                    ]
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        return await inter.send(embed=embed)

    @ranks.sub_command(
        name="list", description="Get a list of players with a specific rank"
    )
    async def list(self, inter: disnake.AppCmdInter, rank: SpecialRank):
        """
        Parameters
        ----------
        rank: The rank to list
        """
        rank_list = await get_rank_list(rank)
        rank_list.sort(key=lambda player: player["name"].lower())
        color = constants.RANK_COLORS.get(rank, constants.DEFAULT_EMBED_COLOR)
        embeds = [
            disnake.Embed(
                title=f"{format_rank(rank)} Ranks! ({len(rank_list)})",
                description="",
                color=color,
            )
        ]
        index = 0
        for i, player in enumerate(rank_list):
            cur = embeds[index]
            desc = cur.description or ""
            if len(desc) >= 1000:
                index += 1
                embeds.append(
                    disnake.Embed(
                        title=f"{format_rank(rank)} Ranks! ({len(rank_list)})",
                        description="",
                        color=color,
                    )
                )
                cur = embeds[index]
                desc = cur.description or ""
            desc += utils.esc_mrkdwn(player["name"]) + (
                ", " if i < len(rank_list) - 1 else ""
            )
            cur.description = desc
        if len(embeds) == 1:
            return await inter.send(embed=utils.add_footer(embeds[0]))
        view = RankListView(embeds, inter)
        await inter.send(embed=view.embeds[view.page], view=view)

    async def poll(self):
        await self.do_watchlist()
        player_ranks = await get_player_ranks()
        if not self.data.to_dict():
            await self.data.replace(player_ranks)
            await self.update_stat_channels(player_ranks)
            logger.info("wrote rank data to empty ranks.json")
            return
        if shrunken := shrunken_ranks(self.data.to_dict(), player_ranks):
            changes = frozenset(
                (uuid, old["rank"], player_ranks.get(uuid, {}).get("rank"))
                for uuid, old in self.data.items()
                if old["rank"] != player_ranks.get(uuid, {}).get("rank")
            )
            self.shrunken_polls = (
                self.shrunken_polls + 1 if changes == self.shrunken_changes else 1
            )
            self.shrunken_changes = changes
            if self.shrunken_polls < self.confirm_polls:
                # A partial API response would announce mass rank removals.
                # Refetch and require the same result before trusting it.
                logger.error(
                    "Rank lists shrank by more than half for %s. Check %s of %s.",
                    ", ".join(shrunken),
                    self.shrunken_polls,
                    self.confirm_polls,
                )
                invalidate_rank_lists()
                return
        self.shrunken_polls = 0
        self.shrunken_changes = None
        for uuid, data in player_ranks.items():
            old_data: dict[str, Any] | None = self.data.get(uuid)
            if not old_data:
                await self.notify_change(
                    ("add", uuid, data["rank"]),
                    self.on_rank_add,
                    uuid,
                    data["name"],
                    data["rank"],
                )
                continue
            if old_data["rank"] != data["rank"]:
                await self.notify_change(
                    ("change", uuid, old_data["rank"], data["rank"]),
                    self.on_rank_change,
                    uuid,
                    data["name"],
                    old_data["rank"],
                    data["rank"],
                )
            if old_data["name"] != data["name"]:
                await self.notify_change(
                    ("name", uuid, old_data["name"], data["name"]),
                    self.on_name_change,
                    uuid,
                    old_data["name"],
                    data["name"],
                    data["rank"],
                )
        for uuid, data in self.data.data.items():
            if uuid not in player_ranks:
                await self.notify_change(
                    ("remove", uuid, data["rank"]),
                    self.on_rank_remove,
                    uuid,
                    data["name"],
                    data["rank"],
                )
        # Most polls find no change. Skip rewriting the file for those.
        if player_ranks != self.data.to_dict():
            await self.data.replace(player_ranks)
        self.known_changes.clear()
        await self.update_stat_channels(player_ranks)
