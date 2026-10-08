import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import disnake
from curl_cffi.requests.exceptions import RequestException
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http, mojang
from skypixel.commands.rank_views import RankListView
from skypixel.domain.types import SpecialRank
from skypixel.storage.json import JsonWrapper
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)

URL: str = "https://api.ragingenby.dev/ranks"
RANK_URL: str = URL + "/{}"
COUNTS_URL: str = RANK_URL.format("counts")
RANKNAME_URL: str = "https://api.ragingenby.dev/rankname/{}"
RANK_LIST_CACHE_TTL_SECONDS = 24 * 60 * 60
RANK_LIST_CACHE: dict[str, list[dict[str, str]]] | None = None
RANK_LIST_CACHE_TIME = 0.0
RANK_LIST_CACHE_LOCK = asyncio.Lock()
RANK_LIST_GENERATION = 0
POI_UUIDS: set[str] = set()
WATCH_LIST_LIMIT = 25


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
    bot: commands.InteractionBot, rank_data: dict[str, list[dict[str, str]]]
):
    rank_data = rank_data.copy()
    rank_data["special"] = [
        player
        for key, players in rank_data.items()
        if key not in constants.RANK_TRACKER_CHANNELS
        for player in players
    ]
    tasks = []
    for rank in constants.RANK_TRACKER_CHANNELS:
        players = rank_data.get(rank, [])
        channels = constants.RANK_TRACKER_CHANNELS[rank]
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


async def get_rank_lists() -> dict[SpecialRank, list[dict[str, str]]]:
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


async def get_player_ranks(
    bot: commands.InteractionBot,
) -> dict[str, dict[str, str | SpecialRank]]:
    data = await get_rank_lists()
    await edit_stat_channels(bot, data)
    return {
        player["id"]: {"rank": rank, "name": player["name"]}
        for rank, players in data.items()
        for player in players
    }


async def send(
    bot: commands.InteractionBot,
    rank: Literal["special"] | SpecialRank,
    embed: disnake.Embed,
    ping: bool = True,
):
    if rank not in constants.RANK_TRACKER_CHANNELS:
        rank = "special"
    await utils.broadcast(
        bot, constants.RANK_TRACKER_CHANNELS[rank], embed=embed, ping=ping
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
    if rank.lower() == "staff":
        return "[ዞ]"
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

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "ranks.json")
        self.watch_list = JsonWrapper(bot.settings.storage_dir / "rankwatchlist.json")
        if not self.data.to_dict():
            logger.warning("ranks.json is empty")
        self.known_changes: set[tuple[str, ...]] = set()
        self.shrunken_polls = 0

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
        await send(self.bot, rank, embed)

    async def on_rank_remove(self, uuid: str, name: str, rank: SpecialRank):
        embed = make_embed(
            uuid,
            name,
            rank,
            f"{utils.esc_mrkdwn(name)} has lost {format_rank(rank)} rank",
        )
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
        await send(self.bot, rank, embed, ping=False)

    async def do_watchlist(self):
        for uuid, last_rankname in list(self.watch_list.items()):
            try:
                rankname = await get_rankname(uuid)
                logger.info("rank watchlist: %s -> %s", last_rankname, rankname)
                if last_rankname is None:
                    await self.watch_list.set_and_save(uuid, rankname)
                    continue
                if rankname != last_rankname:
                    invalidate_rank_lists()
                    await self.watch_list.remove_and_save(uuid)
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
        name="update", description="Update's a player's rank in my database"
    )
    async def update(self, inter: disnake.AppCmdInter, player: str):
        try:
            rankname = await get_rankname(player)
            invalidate_rank_lists()
        except mojang.PlayerNotFound:
            if not mojang.is_valid_identifier(player):
                return await inter.send(
                    embed=utils.make_error(
                        "Invalid player!",
                        "Enter a Minecraft username or UUID.",
                    )
                )
            return await inter.send(
                embed=utils.make_error(
                    "Player not found!",
                    f"No player named [{player}](https://namemc.com/search?q={player.lower()}) was found. Please check your spelling and try again.",
                )
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
        name="watch", description="Watch a player for rank changes closer than others"
    )
    async def watch(self, inter: disnake.AppCmdInter, player: str):
        try:
            player_obj = await mojang.get(player)
        except mojang.PlayerNotFound:
            return await inter.send(
                embed=utils.make_error(
                    "Player not found!",
                    f"I couldn't find the player `{player.replace('`', '')}`!",
                )
            )
        if len(self.watch_list) >= WATCH_LIST_LIMIT:
            return await inter.send(
                embed=utils.make_error(
                    "Watchlist Full!",
                    f"The watchlist can hold {WATCH_LIST_LIMIT} players. "
                    "Wait for a watched player's rank to change.",
                )
            )
        if player_obj.id in self.watch_list:
            return await inter.send(
                embed=utils.make_error(
                    "Already Watching!",
                    f"`{player_obj.name}` is already in the watchlist.",
                )
            )
        await self.watch_list.set_and_save(player_obj.id, None)
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
        name="counts", description="Get the amount of players with each rank"
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
        player_ranks = await get_player_ranks(self.bot)
        if not self.data.to_dict():
            await self.data.replace(player_ranks)
            logger.info("wrote rank data to empty ranks.json")
            return
        if shrunken := shrunken_ranks(self.data.to_dict(), player_ranks):
            self.shrunken_polls += 1
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
                    ("add", uuid, data["rank"]),
                    self.on_rank_add,
                    uuid,
                    data["name"],
                    data["rank"],
                )
                await self.notify_change(
                    ("remove", uuid, old_data["rank"]),
                    self.on_rank_remove,
                    uuid,
                    data["name"],
                    old_data["rank"],
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
        await self.data.replace(player_ranks)
        self.known_changes.clear()
