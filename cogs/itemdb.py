from typing import Any
import disnake
from disnake.ext import commands
import asyncio

from modules import mongodb
from modules import mojang
from modules import utils

import constants


def fix_item(item: dict[str, Any]) -> dict[str, Any]:
    """
    Over the time my itemdb has existed, I've done various stupid things to mess up data.
    Although I am in the process of fixing all of them, this function will sanitize
    the item to ENSURE that it is not one of those.
    """
    # these all come from one update query where i intended to convert unix -> timestamp obj's
    if item['previousOwners'].get('$map'):
        item['previousOwners'] = []
    if isinstance(item.get('lastChecked'), dict):
        item['lastChecked'] = 1
    if isinstance(item.get('start'), dict):
        item['start'] = 1
    if isinstance(item.get('createdAt'), dict):
        item['createdAt'] = 1
    return item
    

async def make_item_embed(item: dict[str, Any]) -> disnake.Embed:
    item = fix_item(item)
    previous_owners = item['previousOwners'][:5]
    players = await mojang.bulk(
        item['currentOwner']['playerUuid'] + 
        [po['playerUuid'] for po in previous_owners]
    )
    
    embed = disnake.Embed(
        title=item.get('friendlyName', item['itemId']),
        color=constants.RARITY_COLORS.get(item['rarity'], constants.DEFAULT_EMBED_COLOR)
    )

    owner = players.get(item['currentOwner']['playerUuid'])
    owner_name = owner.name if owner else item['currentOwner']['playerUuid']
    embed.set_author(
        name=owner_name,
        icon_url=owner.avatar if owner else None,
        url="https://sky.shiiyu.moe/stats/" + item['currentOwner']['playerUuid']
    )
    
    embed.add_field(
        name="UUID",
        value=item['_id'],
        inline=True
    )
    
    embed.add_field(
        name="Current Owner",
        value=f"{owner_name} (<t:since {item['start'] // 1000}:d>)\n-# Item last seen <t:{item['lastChecked'] // 1000}:d>",
        inline=True
    )
    
    if previous_owners:
        # as a BIG oneliner fan i REALLY wanted to do this in a oneliner
        # but because of how i get players from mojang that is not possible💔
        lines = []
        for po in previous_owners:
            player = players.get(po['playerUuid'])
            player_name = player.name if player else po['playerUuid']
            lines.append(f"{player_name} (<t:{po['start'] // 1000}:d> - <t:{po['end'] // 1000}:d>)")
        embed.add_field(
            name=f"Previous {len(previous_owners)} Owners",
            value='\n'.join(lines),
            inline=False
        )
        
    if item.get('extraAttributes'):
        extra_attributes_text = '\n'.join([f"{k}: {v}" for k, v in item['extraAttributes'].items()])
        embed.add_field(
            name="Extra Attributes",
            value=f"```\n{extra_attributes_text}```",
            inline=True
        )
        
    if item.get('enchantments'):
        enchantments_text = '\n'.join([f"{k}: {v}" for k, v in item['enchantments'].items()])
        embed.add_field(
            name="Enchantments",
            value=f"```\n{enchantments_text}```",
            inline=True
        )

    # attributes is a new field meaning that 99% of items dont have it
    # in the future when more items have it, i will change this styling a little
    if item.get('attributes'):
        attributes_text = '\n'.join([f"{k}: {v}" for k, v in item['attributes'].items()])
        embed.add_field(
            name="Attributes",
            value='\n'.join(attributes_text),
            inline=False
        )
        
    if item.get('createdAt'):
        embed.add_field(
            name="Creation Time",
            value=f"<t:{item['createdAt']}:F>",
            inline=True
        )

    if item.get('rarity'):
        embed.add_field(
            name="Rarity",
            value=item['rarity'],
            inline=True
        )

    if item.get('location'):
        embed.add_field(
            name="Location",
            value=item['location'],
            inline=True
        )

    if item.get('soulbound'):
        embed.add_field(
            name="Soulbound",
            value=item['soulbound'],
            inline=False
        )

    if item.get('colour'):
        exotic_text = f" ({item['exoticType']})" if item.get('exoticType') else ""
        embed.add_field(
            name="Color",
            value='#' + item['colour'] + exotic_text,
            inline=True
        )
    return embed


class ItemSearchCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.item_db = mongodb.Collection("SkyBlock", "items")
        self.bot = bot

    async def do_search_command(self, inter: disnake.AppCmdInter, query: dict[str, Any], limit: int = 1):
        results = await self.item_db.search(query, limit=limit)
        if not results:
            return await inter.send(embed=utils.make_error(
                "No Results Found",
                "Your search yielded no items. Try broadening your search."
            ))
        elif len(results) > 1:
            return await inter.send(embed=utils.make_error(
                "Multiple Results Found",
                "Your search request yielded multiple items. Pages are not yet supported, so for now you gotta be more specific."
            ))
        embed = await make_item_embed(results[0])
        return await inter.send(embed=embed)

    @commands.slash_command(
        name="itemdb",
        description="Commands that use the RagingEnby item database"
    )
    async def itemdb(self, inter: disnake.AppCmdInter):
        await inter.response.defer()

    @itemdb.sub_command(
        name="clay-search",
        description="Search for a Builder's Clay item"
    )
    async def clay_search_cmd(self, inter: disnake.AppCmdInter, edition: int):
        return await self.do_search_command(inter, {
            "itemId": "DUECES_BUILDER_CLAY",
            "edition": edition
        })

    @commands.Cog.listener()
    async def on_ready(self):
        def signal_handler(sig: int, _):
            asyncio.create_task(self.item_db.close())

