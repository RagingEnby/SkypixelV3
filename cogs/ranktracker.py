import disnake
from disnake.ext import commands
import asyncio
import traceback

from modules import asyncreqs
from modules import datamanager
from modules import utils

import constants


URL: str = "https://api.ragingenby.dev/ranks"
COUNTS_URL: str = URL + '/counts'
RANKNAME_URL: str = "https://api.ragingenby.dev/rankname/{}"


async def get_rankname(identifier: str) -> str:
    response = await asyncreqs.get(RANKNAME_URL.format(identifier))
    data = await response.json()
    return data['rankname']


async def get_rank_counts() -> dict[str, int]:
    response = await asyncreqs.get(COUNTS_URL)
    data: dict[str, int] = await response.json()
    # sort highest -> lowest count
    return dict(sorted(data.items(), key=lambda item: item[1], reverse=True))


async def get_rank_lists() -> dict[str, list[dict[str, str]]]:
    response = await asyncreqs.get(URL)
    return await response.json()


async def get_player_ranks() -> dict[str, dict[str, str]]:
    data = await get_rank_lists()
    return {
        player['id']: {
            "rank": rank,
            "name": player['name']
        } for rank, players in data.items()
        for player in players
    }


async def send(rank: str, embed: disnake.Embed):
    if rank not in constants.RANK_TRACKER_CHANNELS:
        rank = 'special'
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.RANK_TRACKER_CHANNELS[rank].items()
    ]
    await asyncio.gather(*tasks)


def format_rank(rank: str) -> str:
    return '[' + rank.replace('_plus', '+').replace('_', ' ').upper() + ']'


def make_embed(uuid: str, name: str, rank: str, title: str) -> disnake.Embed:
    embed = utils.add_footer(disnake.Embed(
        title=title,
        color=constants.RANK_COLORS.get(rank, constants.DEFAULT_EMBED_COLOR)
    ))
    return embed.set_author(
        name=f"{format_rank(rank)} {name}",
        icon_url=constants.MC_HEAD_IMAGE.format(uuid)
    )


class RankTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/ranks.json")

    async def on_rank_add(self, uuid: str, name: str, rank: str):
        embed = make_embed(
            uuid, name, rank,
            f"{utils.esc_mrkdwn(name)} now has {format_rank(rank)} rank!"
        )
        await send(rank, embed)

    async def on_rank_remove(self, uuid: str, name: str, rank: str):
        embed = make_embed(
            uuid, name, rank,
            f"{utils.esc_mrkdwn(name)} has lost {format_rank(rank)} rank"
        )
        await send(rank, embed)
        
    async def on_name_change(self, uuid: str, before: str, after: str, rank: str):
        embed = make_embed(
            uuid, after, rank,
            f"{utils.esc_mrkdwn(before)} changed their IGN to {utils.esc_mrkdwn(after)}"
        )
        await send(rank, embed)
        
    async def main(self):
        while True:
            try:
                player_ranks = await get_player_ranks()
                for uuid, data in player_ranks.items():
                    if uuid not in self.data:
                        await self.on_rank_add(uuid, data['name'], data['rank'])
                        continue
                    if self.data[uuid]['rank'] != data['rank']:
                        await self.on_rank_add(uuid, data['name'], data['rank'])
                        await self.on_rank_remove(uuid, data['name'], self.data[uuid]['rank'])
                    if self.data[uuid]['name'] != data['name']:
                        await self.on_name_change(
                            uuid=uuid,
                            before=self.data[uuid]['name'],
                            after=data['name'],
                            rank=data['rank']
                        )
                for uuid, data in self.data.data.items():
                    if uuid not in player_ranks:
                        await self.on_rank_remove(uuid, data['name'], data['rank'])
                        
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
        embed = embed=utils.add_footer(disnake.Embed(
            description=f"Successfully updated `{unformatted}`",
            color=disnake.Color.green()
        ))
        embed.set_image(url=utils.to_mc_text(rankname))
        return await inter.send(embed=embed)

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
                f"**{format_rank(rank)}:** `{count}`"
                for rank, count in counts.items()
            ]),
            color=constants.DEFAULT_EMBED_COLOR
        ))
        return await inter.send(embed=embed)
        