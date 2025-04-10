import asyncio
import traceback
from contextlib import suppress
from typing import Literal

import disnake
import requests
from disnake.ext import commands

import constants
from modules import asyncreqs, mojang
from modules import datamanager
from modules import utils

SpecialRank = Literal['youtube', 'admin', 'gm', 'owner', 'pig_plus_plus_plus', 'innit', 'events', 'mojang', 'mcp']

URL: str = "https://api.ragingenby.dev/ranks"
RANK_URL: str = URL + '/{}'
COUNTS_URL: str = URL + '/counts'
RANKNAME_URL: str = "https://api.ragingenby.dev/rankname/{}"
POI_UUIDS: set[str] = {
    player['id']
    for players in requests.get(URL).json().values()
    for player in players
}
WATCH_LIST: datamanager.JsonWrapper = datamanager.JsonWrapper("storage/rankwatchlist.json")


async def get_rankname(identifier: str) -> str:
    response = await asyncreqs.get(RANKNAME_URL.format(identifier))
    data = await response.json()
    return data['rankname']


async def get_rank_counts() -> dict[str, int]:
    response = await asyncreqs.get(COUNTS_URL)
    data: dict[str, int] = await response.json()
    # sort highest -> lowest count
    return dict(sorted(data.items(), key=lambda item: item[1], reverse=True))


async def get_rank_lists() -> dict[SpecialRank, list[dict[str, str]]]:
    global POI_UUIDS
    response = await asyncreqs.get(URL)
    data = await response.json()
    POI_UUIDS = {
        player['id']
        for players in data.values()
        for player in players
    }
    return data


async def get_rank_list(rank: SpecialRank) -> list[dict[str, str]]:
    response = await asyncreqs.get(RANK_URL.format(rank))
    return await response.json()


async def get_player_ranks() -> dict[str, dict[str, str | SpecialRank]]:
    data = await get_rank_lists()
    return {
        player['id']: {
            "rank": rank,
            "name": player['name']
        } for rank, players in data.items()
        for player in players
    }


async def send(rank: Literal['special'] | SpecialRank, embed: disnake.Embed):
    if rank not in constants.RANK_TRACKER_CHANNELS:
        rank = 'special'
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.RANK_TRACKER_CHANNELS[rank].items()
    ]
    await asyncio.gather(*tasks)


def format_rank(rank: str) -> str:
    return '[' + rank.replace('_plus', '+').replace('_', ' ').upper() + ']'


def make_embed(uuid: str, name: str, rank: SpecialRank, title: str) -> disnake.Embed:
    embed = utils.add_footer(disnake.Embed(
        title=title,
        color=constants.RANK_COLORS.get(rank, constants.DEFAULT_EMBED_COLOR)
    ))
    return embed.set_author(
        name=f"{format_rank(rank)} {name}",
        icon_url=constants.MC_HEAD_IMAGE.format(uuid)
    )


class RankListView(disnake.ui.View):
    def __init__(self, embeds: list[disnake.Embed], inter: disnake.Interaction):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.inter = inter
        self.page = 0

    async def interaction_check(self, interaction: disnake.Interaction) -> bool:
        if interaction.user != self.inter.user:
            await interaction.response.send_message(embed=utils.make_error(
                "Not your interaction!",
                "You cannot interact with another user's buttons."
            ), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, disnake.ui.Button):
                item.disabled = True
        with suppress(disnake.NotFound, disnake.HTTPException):
            await self.inter.edit_original_message(view=self)

    async def _update_buttons(self):
        self.children[0].disabled = self.page == 0 # previous
        self.children[1].disabled = self.page == len(self.embeds) - 1 # next
        current_embed = self.embeds[self.page]
        current_embed.set_footer(
            text=f"Page {self.page+1}/{len(self.embeds)}"
        )

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="⬅️", row=0)
    async def previous(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        self.page -= 1
        await self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="➡️", row=0)
    async def next(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        self.page += 1
        await self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)


class RankTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/ranks.json")

    async def on_rank_add(self, uuid: str, name: str, rank: SpecialRank):
        embed = make_embed(
            uuid, name, rank,
            f"{utils.esc_mrkdwn(name)} now has {format_rank(rank)} rank!"
        )
        await send(rank, embed)

    async def on_rank_remove(self, uuid: str, name: str, rank: SpecialRank):
        embed = make_embed(
            uuid, name, rank,
            f"{utils.esc_mrkdwn(name)} has lost {format_rank(rank)} rank"
        )
        await send(rank, embed)
        
    async def on_name_change(self, uuid: str, before: str, after: str, rank: SpecialRank):
        embed = make_embed(
            uuid, after, rank,
            f"{utils.esc_mrkdwn(before)} changed their IGN to {utils.esc_mrkdwn(after)}"
        )
        await send(rank, embed)

    async def do_watchlist(self):
        for uuid, last_rankname in WATCH_LIST.items():
            rankname = await get_rankname(uuid)
            print('rank watchlist:', rankname, last_rankname)
            if last_rankname is None:
                WATCH_LIST[uuid] = rankname
                await WATCH_LIST.save()
                continue
            if rankname != last_rankname:
                del WATCH_LIST[uuid]
                await WATCH_LIST.save()
        
    async def main(self):
        while True:
            try:
                await self.do_watchlist()
                player_ranks = await get_player_ranks()
                if self.data.to_dict():
                    for uuid, data in player_ranks.items():
                        if uuid not in self.data:
                            await self.on_rank_add(uuid, data['name'], data['rank'])  # type: ignore
                            continue
                        if self.data[uuid]['rank'] != data['rank']:
                            await self.on_rank_add(uuid, data['name'], data['rank'])  # type: ignore
                            await self.on_rank_remove(uuid, data['name'], self.data[uuid]['rank'])
                        if self.data[uuid]['name'] != data['name']:
                            await self.on_name_change(
                                uuid=uuid,
                                before=self.data[uuid]['name'],
                                after=data['name'],
                                rank=data['rank']  # type: ignore
                            )
                    for uuid, data in self.data.data.items():
                        if uuid not in player_ranks:
                            await self.on_rank_remove(uuid, data['name'], data['rank'])  # type: ignore
                            
                self.data.data = player_ranks
                await self.data.save()
                await asyncio.sleep(120)
            except Exception:
                print("rank tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())

    @commands.slash_command(
        name="ranks",
        description="Various utilities relating to Special Hypixel ranks!"
    )
    async def ranks(self, inter: disnake.AppCmdInter):
        await inter.response.defer()

    @ranks.sub_command(
        name="update",
        description="Update's a player's rank in my database"
    )
    async def update(self, inter: disnake.AppCmdInter, player: str):
        rankname = await get_rankname(player)
        unformatted = utils.remove_color_codes(rankname)
        embed = utils.add_footer(disnake.Embed(
            description=f"Successfully updated `{unformatted}`",
            color=disnake.Color.green()
        ))
        embed.set_image(url=utils.to_mc_text(rankname))
        return await inter.send(embed=embed)

    @ranks.sub_command(
        name="watch",
        description="Watch a player for rank changes closer than others"
    )
    async def watch(self, inter: disnake.AppCmdInter, player: str):
        try:
            player_obj = await mojang.get(player)
        except mojang.PlayerNotFound:
            return await inter.send(embed=utils.make_error(
                "Player not found!",
                f"I couldn't find the player `{player}`!"
            ))
        if player_obj.id in WATCH_LIST:
            return await inter.send(embed=utils.make_error(
                "Already Watching!",
                f"`{player_obj}` is already in the watchlist."
            ))
        WATCH_LIST[player_obj.id] = None
        await WATCH_LIST.save()
        await inter.send(embed=utils.add_footer(disnake.Embed(
            title="Added To Watchlist",
            description=f"Now tracking `{player_obj.name}` for rank changes!",
            color=constants.DEFAULT_EMBED_COLOR
        )))
        

    @ranks.sub_command(
        name="counts",
        description="Get the amount of players with each rank"
    )
    async def counts(self, inter: disnake.AppCmdInter):
        counts = await get_rank_counts()
        del counts['normal']
        embed = utils.add_footer(disnake.Embed(
            title="Rank Counts",
            description='\n'.join([
                f"**{format_rank(rank)}:** `{utils.commaize(count)}`"
                for rank, count in counts.items()
            ]),
            color=constants.DEFAULT_EMBED_COLOR
        ))
        return await inter.send(embed=embed)

    @ranks.sub_command(
        name="list",
        description="Get a list of players with a specific rank"
    )
    async def list(self, inter: disnake.AppCmdInter, rank: SpecialRank):
        rank_list = await get_rank_list(rank)
        color = constants.RANK_COLORS.get(rank, constants.DEFAULT_EMBED_COLOR)
        embeds = [disnake.Embed(
            title=f"{format_rank(rank)} Ranks! ({len(rank_list)})",
            description="",
            color=color
        )]
        index = 0
        for player in rank_list:
            if len(embeds[index].description) >= 1000:
                index += 1
                embeds.append(disnake.Embed(
                    title=f"{format_rank(rank)} Ranks! ({len(rank_list)})",
                    description="",
                    color=color
                ))
            embeds[index].description += f"{utils.esc_mrkdwn(player['name'])}, "
        if len(embeds) == 1:
            return await inter.send(embed=utils.add_footer(embeds[0]))
        view = RankListView(embeds, inter)
        await inter.send(embed=embeds[0], view=view)
        await view._update_buttons()
