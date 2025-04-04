from typing import Any
import disnake
from disnake.ext import commands
import asyncio
import json

from modules import hypixel, mongodb
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
    if isinstance(item['previousOwners'], dict):
        item['previousOwners'] = []
    if isinstance(item.get('lastChecked'), dict):
        item['lastChecked'] = 1
    if isinstance(item.get('start'), dict):
        item['start'] = 1
    if isinstance(item.get('createdAt'), dict):
        item['createdAt'] = 1
    return item


def get_item_image(item: dict[str, Any]) -> str:
    default = constants.ITEM_IMAGE.format(item['itemId'])
    if not item.get('colour'):
        return default
    try:
        material = hypixel.get_material(item['itemId'])
    except KeyError as e:
        print('unable to find material for item:', e)
        return default
    if not material.startswith('LEATHER_'):
        return default
    armor_type = material.replace('LEATHER_', '').lower()
    return constants.LEATHER_IMAGE.format(armor_type, item['colour'])
    

async def make_item_embed(item: dict[str, Any]) -> disnake.Embed:
    item = fix_item(item)
    print(json.dumps(item, indent=2))
    previous_owners = list(reversed(item['previousOwners']))[:5]
    players = await mojang.bulk(
        [item['currentOwner']['playerUuid']] + 
        [po['owner']['playerUuid'] for po in previous_owners]
    )
    
    embed = disnake.Embed(
        title=utils.remove_color_codes(item.get('friendlyName', item['itemId'])),
        color=constants.RARITY_COLORS.get(item['rarity'], constants.DEFAULT_EMBED_COLOR)
    )
    embed.set_thumbnail(url=get_item_image(item))

    owner = players.get(item['currentOwner']['playerUuid'])
    owner_name = utils.esc_mrkdwn(owner.name) if owner else item['currentOwner']['playerUuid']
    embed.set_author(
        name=owner_name,
        icon_url=owner.avatar if owner else None,
        url="https://sky.shiiyu.moe/stats/" + item['currentOwner']['playerUuid']
    )
    
    embed.add_field(
        name="UUID",
        value=f"{item['_id']}\n-# **Cofl UID:** {item['coflUid']}",
        inline=True
    )
    
    embed.add_field(
        name="Current Owner",
        value=f"{owner_name} (since <t:{item['start'] // 1000}:d>)\n-# Item last seen <t:{item['lastChecked'] // 1000}:d>",
        inline=True
    )
    
    if previous_owners:
        # as a BIG oneliner fan i REALLY wanted to do this in a oneliner
        # but because of how i get players from mojang that is not possible💔
        lines = []
        for po in previous_owners:
            player = players.get(po['owner']['playerUuid'])
            player_name = utils.esc_mrkdwn(player.name) if player else po['owner']['playerUuid']
            lines.append(f"{player_name} (<t:{po['start'] // 1000}:d> - <t:{po['end'] // 1000}:d>)")
        embed.add_field(
            name=f"Previous {len(previous_owners)} Owners",
            value='\n'.join(lines),
            inline=False
        )
    else:
        # 'linebreak' field
        embed.add_field(
            name=" ",
            value=" ",
            inline=True
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
            value=f"```\n{attributes_text}```",
            inline=False
        )
    else:
        # 'line break' (seperates the inlines)
        embed.add_field(
            name="",
            value=" ",
            inline=False
        )

    if item.get('lore'):
        lore_text = '\n'.join([utils.remove_color_codes(line) for line in item['lore']])[:1010]
        embed.add_field(
            name="Lore",
            value=f"```\n{lore_text}```",
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


def make_in_regex(playername: str) -> dict[str, str]:
    return {"$regex": playername, "$options": "i"}


class ItemSearchCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.item_db = mongodb.Collection("SkyBlock", "itemdb")
        self.bot = bot

    async def do_search_command(self, inter: disnake.AppCmdInter, query: dict[str, Any], limit: int = 1):
        query = {k: v for k, v in query.items() if v is not None}
        if len(query) == 1 and query.get('itemId'):
            return await inter.send(embed=utils.make_error(
                "Invalid Query",
                "You must provide search arguments!"
            ))
        print('searching item db for:', json.dumps(query, indent=2))
        results = await self.item_db.search(query, limit=limit)
        if not results:
            return await inter.send(embed=utils.make_error(
                "No Results Found",
                "Your search yielded no items. Try broadening your search."
            ))
        """elif len(results) > 1:
            return await inter.send(embed=utils.make_error(
                f"Multiple Results Found ({len(results)})",
                "Your search request yielded multiple items. Pages are not yet supported, so for now you gotta be more specific."
            ))"""
        embed = await make_item_embed(results[0])
        return await inter.send(embed=embed)

    @commands.slash_command(
        name="itemdb",
        description="Commands that use the RagingEnby item database"
    )
    async def itemdb(self, inter: disnake.AppCmdInter):
        await inter.response.defer()

    @itemdb.sub_command(
        name="search",
        description="**ADMIN ONLY** Search the item database using json params"
    )
    async def search(self, inter: disnake.AppCmdInter, query: str):
        try:
            return await self.do_search_command(inter, json.loads(query))
        except json.JSONDecodeError as e:
            return await inter.send(embed=utils.make_error(
                "Invalid JSON",
                e
            ))

    @itemdb.sub_command(
        name="clay-search",
        description="Search the itemdb for a Builder's Clay"
    )
    async def clay_search_cmd(self, inter: disnake.AppCmdInter,
                              edition: int | None = None, sender_name: str | None = None,
                              recipient_name: str | None = None):
        return await self.do_search_command(inter, {
           "itemId": "DUECES_BUILDER_CLAY",
           "extraAttributes.edition": edition,
           "extraAttributes.sender": make_in_regex(sender_name) if sender_name else None,
           "extraAttributes.recipient_name": make_in_regex(recipient_name) if recipient_name else None,
       })

    @itemdb.sub_command(
        name="basket-search",
        description="Search the itemdb for a Basket of Hope"
    )
    async def basket_search_cmd(self, inter: disnake.AppCmdInter,
                                edition: int | None = None, basket_player_name: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": "POTATO_BASKET",
            "extraAttributes.basket_edition": edition,
            "extraAttributes.basket_player_name": make_in_regex(basket_player_name) if basket_player_name else None
        })

    @itemdb.sub_command(
        name="elevator-search",
        description="Search the itemdb for an Ancient Elevator"
    )
    async def elevator_search_cmd(self, inter: disnake.AppCmdInter,
                                  edition: int | None = None, sender_name: str | None = None,
                                  recipient_name: str | None = None):
        return await self.do_search_command(inter, {
           "itemId": "ANCIENT_ELEVATOR",
           "extraAttributes.edition": edition,
           "extraAttributes.sender": make_in_regex(sender_name) if sender_name else None,
           "extraAttributes.recipient_name": make_in_regex(recipient_name) if recipient_name else None,
       })

    @itemdb.sub_command(
        name="memento-search",
        description="Search the itemdb for a Memento"
    )
    async def memento_search_cmd(self, inter: disnake.AppCmdInter,
                                 memento: hypixel.Memento | None = None,
                                 edition: int | None = None, recipient_name: str | None = None,
                                 recipient_id: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": memento if memento else {"$in": hypixel.MEMENTOS},
            "extraAttributes.edition": edition,
            "extraAttributes.recipient_name": make_in_regex(recipient_name) if recipient_name else None,
            "extraAttributes.recipient_id": recipient_id
        })

    @itemdb.sub_command(
        name="racinghelm-search",
        description="Search the itemdb for a Racing Helmet"
    )
    async def racinghelm_search_cmd(self, inter: disnake.AppCmdInter,
                                    edition: int | None = None, auction: int | None = None,
                                    bid: int | None = None, price: int | None = None,
                                    buyer: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": "RACING_HELMET",
            "extraAttributes.edition": edition,
            "extraAttributes.auction": auction,
            "extraAttributes.bid": bid,
            "extraAttributes.price": price,
            "extraAttributes.player": make_in_regex(buyer) if buyer else None
        })

    @itemdb.sub_command(
        name="spacehelm-search",
        description="Search the itemdb for a (Dctr) Space Helmet"
    )
    async def spacehelm_search_cmd(self, inter: disnake.AppCmdInter,
                                   edition: int | None = None, sender_name: str | None = None,
                                   recipient_name: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": "DCTR_SPACE_HELM",
            "extraAttributes.edition": edition,
            "extraAttributes.sender_name": make_in_regex(sender_name) if sender_name else None,
            "extraAttributes.recipient_name": make_in_regex(recipient_name) if recipient_name else None
        })

    @commands.Cog.listener()
    async def on_ready(self):
        def signal_handler(sig: int, _):
            asyncio.create_task(self.item_db.close())

