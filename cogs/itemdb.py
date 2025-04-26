import json
import logging
import re
from contextlib import suppress
from typing import Any, Optional, Literal

import disnake
import pymongo
from disnake.ext import commands

import constants
from modules import hypixel, mongodb
from modules import mojang
from modules import utils

logger = logging.getLogger(__name__)
PrefixRank = Literal['NON', '[VIP]', '[VIP+]', '[MVP]', '[MVP+]',
                   '[MVP++]', '[YOUTUBE]', '[PIG+++]', '[INNIT]',
                   '[MINISTER]', '[MAYOR]', '[MOJANG]', '[EVENTS]',
                   '[HELPER]', '[MOD]', '[GM]', '[ADMIN]', '[OWNER]', '[ዞ]']


def fix_item(item: dict[str, Any]) -> dict[str, Any]:
    """
    Over the time my itemdb has existed, I've done various stupid things to mess up data.
    Although I am in the process of fixing all of them, this function will sanitize
    the item to ENSURE that it is not one of those.
    """
    logger.debug(f"fixing item: {item}")
    # these all come from one update query where i intended to convert unix -> timestamp obj's
    if isinstance(item['previousOwners'], dict):
        item['previousOwners'] = []
    if isinstance(item.get('lastChecked'), dict):
        item['lastChecked'] = 0
    if isinstance(item.get('start'), dict):
        item['start'] = 0
    if isinstance(item.get('createdAt'), dict):
        item['createdAt'] = 0
    # throwback to the time my dumbass fucked up capitaliation
    if item.get('createdAt'):
        item['created_at'] = item.pop('createdAt')
    return item


def get_item_image(item: dict[str, Any]) -> str:
    return utils.get_item_image(
        item_id=item['itemId'],
        color=item.get('colour'),
        durability=item.get('damage')
    )
    

async def make_item_embed(item: dict[str, Any]) -> disnake.Embed:
    item = fix_item(item)
    previous_owners = list(reversed(item['previousOwners']))[:5]
    players = await mojang.bulk(
        [item['currentOwner']['playerUuid']] + 
        [po['owner']['playerUuid'] for po in previous_owners]
    )
    
    embed = utils.add_footer(disnake.Embed(
        title=utils.remove_color_codes(item.get('friendlyName', item['itemId'])),
        color=constants.RARITY_COLORS.get(item['rarity'], constants.DEFAULT_EMBED_COLOR)
    ))
    embed.set_thumbnail(url=get_item_image(item))

    owner = players.get(item['currentOwner']['playerUuid'])
    owner_name = owner.name if owner else item['currentOwner']['playerUuid']
    embed.set_author(
        name=owner_name,
        icon_url=owner.avatar if owner else None,
        url="https://sky.shiiyu.moe/stats/" + item['currentOwner']['playerUuid']
    )
    
    embed.add_field(
        name="UUID",
        value=f"{item['_id']}\n-# **Cofl UID:** {item['coflUid']}",
        inline=False
    )
    
    embed.add_field(
        name="Current Owner",
        value=f"{utils.esc_mrkdwn(owner_name)} (since <t:{item['start'] // 1000}:d>)\n-# Item last seen <t:{item['lastChecked'] // 1000}:d>",
        inline=False
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

    if item.get('created_at'):
        embed.add_field(
            name="Creation Time",
            value=f"<t:{item['created_at'] // 1000}:f>",
            inline=True
        )

    if item.get('rarity'):
        embed.add_field(
            name="Rarity",
            value=item['rarity'],
            inline=True
        )

    if item.get('soulbound'):
        embed.add_field(
            name="Soulbound",
            value=item['soulbound'],
            inline=True
        )

    if item.get('reforge'):
        embed.add_field(
            name="Reforge",
            value=item['reforge'],
            inline=True
        )

    if item.get('colour'):
        exotic_text = f" ({item['exoticType']})" if item.get('exoticType') else ""
        embed.add_field(
            name="Color",
            value='#' + item['colour'] + exotic_text,
            inline=True
        )

    if item.get('location'):
        embed.add_field(
            name="Location",
            value=item['location'],
            inline=True
        )
    return embed


def make_item_view(item: dict[str, Any]) -> disnake.ui.View:
    view = disnake.ui.View()
    view.add_item(
        disnake.ui.Button(
            label="View Raw Data",
            url="https://api.ragingenby.dev/items/" + item['_id'],
            style=disnake.ButtonStyle.link
        )
    )
    if item.get('lore'):
        view.add_item(
            disnake.ui.Button(
                label="View Lore",
                style=disnake.ButtonStyle.primary,
                custom_id="view_lore|" + item['_id']
            )
        )
    return view


def make_playername_regex(playername: str) -> dict[str, str]:
    color_code_pattern = "(§[0-9a-fk-or])*"
    escaped_name = re.escape(playername)
    return {"$regex": f"(§7| ){escaped_name}{color_code_pattern}$", "$options": "i"}


def make_rank_regex(rank: PrefixRank) -> dict:
    if rank == "NON": # for non ranks, just find names without spaces
        return {"$not": {"$regex": " "}}
    color_code_pattern = "(§[0-9a-fk-or])*"
    escaped_rank_chars = [re.escape(char) for char in rank]
    interspersed_rank = color_code_pattern.join(escaped_rank_chars)
    return {"$regex": f"^{color_code_pattern}{interspersed_rank}"}


def make_player_regex(rank: PrefixRank | None = None, playername: str | None = None) -> dict[str, Any]:
    if not rank and not playername:
        raise ValueError("No arguments provided")
    if rank and not playername:
        return make_rank_regex(rank)  # type: ignore[arg-type]
    if playername:
        return make_playername_regex(playername)
    return {"$and": [make_rank_regex(rank), make_playername_regex(playername)]}  # type: ignore[arg-type]


class SoulSearchView(disnake.ui.View):
    def __init__(self, query: dict, count: int, main_embed: disnake.Embed, item_db: mongodb.Collection, inter: disnake.Interaction):
        super().__init__(timeout=180)
        self.query = query
        self.count = count
        self.main_embed = main_embed
        self.item_db = item_db
        self.inter = inter
        self.index = 0
        self.item_cache: dict[int, dict] = {}
        self.embed_cache: dict[int, disnake.Embed] = {}

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

    async def get_current_item(self) -> dict | None:
        if self.item_cache.get(self.index):
            return self.item_cache[self.index]
        cursor = self.item_db.find(self.query).sort([("extraAttributes.captured_date", pymongo.DESCENDING)])
        cursor.skip(self.index).limit(1)
        try:
            item = await cursor.next()
            self.item_cache[self.index] = item
            return item
        except StopAsyncIteration as e:
            logger.error(f"SoulSearchView() ending iteration for {self.query}: {e}")
            self.count = self.index + 1
            await self.update_buttons()
            return None

    async def get_current_embed(self) -> disnake.Embed | None:
        if self.embed_cache.get(self.index):
            return self.embed_cache[self.index]
        item = await self.get_current_item()
        if not item:
            return None
        embed = await make_item_embed(item)
        embed.set_footer(text=f"Item {self.index+1}/{self.count}")
        self.embed_cache[self.index] = embed
        return embed

    async def update_buttons(self):
        logger.debug("updating buttons")
        self.children[0].disabled = self.index == 0  # type: ignore[index]
        self.children[1].disabled = self.index == self.count - 1  # type: ignore[index]

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="⬅️", row=0)
    async def previous(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        logger.debug("previous button clicked")
        self.index -= 1
        await self.update_buttons()
        embed = await self.get_current_embed()
        if not embed:
            return await interaction.response.edit_message(embeds=[self.main_embed], view=self)
        await interaction.response.edit_message(embeds=[self.main_embed, embed], view=self)

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="➡️", row=0)
    async def next(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        logger.debug("next button clicked")
        self.index += 1
        await self.update_buttons()
        embed = await self.get_current_embed()
        if not embed:
            return await interaction.response.edit_message(embeds=[self.main_embed], view=self)
        await interaction.response.edit_message(embeds=[self.main_embed, embed], view=self)


def search_souls_query(query: dict) -> dict:
    query = {k: v for k, v in query.items() if v is not None}
    query['itemId'] = "CAKE_SOUL"
    if not query.get('extraAttributes.captured_player'):
        query['extraAttributes.captured_player'] = {"$exists": True}
    return query


class ItemDBCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.item_db = mongodb.Collection("SkyBlock", "itemdb")
        self.bot = bot
        self.item_cache: dict[str, dict[str, Any]] = {}

    async def search_souls(self, query: dict) -> dict[str, int]:
        query = search_souls_query(query)
        logger.info(f"searching souls for: {query}")
        # i am FULLY aware this is unreadable and completely illegal
        # however, i made it in mongo compass and i cba to make it
        # readable here
        pipeline = [
            {"$match": query},
            {"$addFields": {"cleaned_player_name": {"$let": {"vars": {"parts": {"$split": ["$extraAttributes.captured_player", "§"]}},"in": {"$reduce": {"input": {"$slice": ["$$parts", 1, {"$size": "$$parts"}]},"initialValue": {"$arrayElemAt": ["$$parts", 0]},"in": {"$concat": ["$$value",{"$substrCP": ["$$this",1,{"$subtract": [{"$strLenCP": "$$this"},1,]},]},]},}},}}}},
            {"$addFields": {"captured_rank": {"$let": {"vars": {"words": {"$split": ["$cleaned_player_name", " "]}},"in": {"$cond": {"if": {"$gte": [{"$size": "$$words"}, 2]},"then": {"$arrayElemAt": ["$$words", 0]},"else": "NON",}},}}}},
            {"$group": {"_id": "$captured_rank", "count": {"$sum": 1}}},
            {"$group": {"_id": None,"ranks": {"$push": {"k": "$_id", "v": "$count"}}}},
            {"$replaceRoot": {"newRoot": {"$arrayToObject": "$ranks"}}},
        ]
        cursor = self.item_db.collection.aggregate(pipeline)
        results = await cursor.to_list(length=1)
        return results[0] if results else {}

    async def get_item_from_uuid(self, uuid: str) -> Optional[dict[str, Any]]:
        if self.item_cache.get(uuid):
            return self.item_cache[uuid]
        item = await self.item_db.find_one({"_id": uuid})
        if item:
            self.item_cache[uuid] = item
        return item

    async def do_search_command(self, inter: disnake.AppCmdInter, query: dict[str, Any], limit: int = 1):
        query = {k: v for k, v in query.items() if v is not None}
        if len(query) == 1 and query.get('itemId'):
            return await inter.send(embed=utils.make_error(
                "Invalid Query",
                "You must provide search arguments!"
            ))
        logger.info(f'searching item db for: {json.dumps(query, indent=2)}')
        results = await self.item_db.search(query, limit=limit)
        if not results:
            return await inter.send(embed=utils.make_error(
                "No Results Found",
                "Your search yielded no items. Try broadening your search."
            ))
        """
        elif len(results) > 1:
            return await inter.send(embed=utils.make_error(
                f"Multiple Results Found ({len(results)})",
                "Your search request yielded multiple items. Pages are not yet supported, so for now you gotta be more specific."
            ))
        """
        self.item_cache.update({item['_id']: item for item in results})
        embed = await make_item_embed(results[0])
        view = make_item_view(results[0])
        return await inter.send(embed=embed, view=view)

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
            parsed_query = json.loads(query)
        except json.JSONDecodeError as e:
            parsed_query = {"_id": query}
        return await self.do_search_command(inter, parsed_query)

    @itemdb.sub_command(
        name="soul-search",
        description="Searches the item database to see how many souls have been captured of a user"
    )
    async def soul_search_cmd(self, inter: disnake.AppCmdInter,
                              captured_rank: PrefixRank | None = None, captured_player: str | None = None,
                              captured_by_rank: PrefixRank | None = None, captured_by_name: str | None = None,
                              cake_owner_rank: PrefixRank | None = None, cake_owner_name: str | None = None):
        query = search_souls_query({
            "itemId": "CAKE_SOUL",
            "extraAttributes.captured_player": make_player_regex(captured_rank, captured_player) if captured_player or captured_rank else None,
            "extraAttributes.initiator_player": make_player_regex(captured_by_rank, captured_by_name) if captured_by_name or captured_by_rank else None,
            "extraAttributes.cake_owner": make_player_regex(cake_owner_rank, cake_owner_name) if cake_owner_name or cake_owner_rank else None
        })
        results = await self.search_souls(query)
        logger.info(json.dumps(results, indent=2))
        if not results:
            return await inter.send(embed=utils.make_error(
                "No Results Found",
                "No Cake Souls were found with this description."
            ))
        embed = utils.add_footer(disnake.Embed(
            title="Soul Search Output",
            color=constants.COLOR_CODES['c']
        ))
        embed.set_thumbnail(utils.get_item_image("CAKE_SOUL"))
        for rank, count in results.items():
            embed.add_field(
                name=rank,
                value=count,
                inline=True
            )
        total = sum(results.values())
        if total > 1:
            view = SoulSearchView(query=query, count=total, main_embed=embed, item_db=self.item_db, inter=inter)
            item_embed = await view.get_current_embed()
            await view.update_buttons()
            await inter.send(embeds=[embed, item_embed], view=view)
        else:
            result = await self.item_db.find_one(query)
            item_embed = await make_item_embed(result)
            await inter.send(embeds=[embed, item_embed])

    @itemdb.sub_command(
        name="clay-search",
        description="Search the itemdb for a Builder's Clay"
    )
    async def clay_search_cmd(self, inter: disnake.AppCmdInter,
                              edition: int | None = None, sender_rank: PrefixRank | None = None,
                              sender_name: str | None = None, recipient_rank: PrefixRank | None = None,
                              recipient_name: str | None = None):
        return await self.do_search_command(inter, {
           "itemId": "DUECES_BUILDER_CLAY",
           "extraAttributes.edition": edition,
           "extraAttributes.sender": make_player_regex(sender_rank, sender_name) if sender_name or sender_rank else None,
           "extraAttributes.recipient_name": make_player_regex(recipient_rank, recipient_name) if recipient_name or recipient_rank else None,
       })

    @itemdb.sub_command(
        name="basket-search",
        description="Search the itemdb for a Basket of Hope"
    )
    async def basket_search_cmd(self, inter: disnake.AppCmdInter,
                                edition: int | None = None, basket_player_rank: PrefixRank | None = None,
                                basket_player_name: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": "POTATO_BASKET",
            "extraAttributes.basket_edition": edition,
            "extraAttributes.basket_player_name": make_player_regex(basket_player_rank, basket_player_name)\
                                                  if basket_player_name or basket_player_rank else None
        })

    @itemdb.sub_command(
        name="elevator-search",
        description="Search the itemdb for an Ancient Elevator"
    )
    async def elevator_search_cmd(self, inter: disnake.AppCmdInter,
                                  edition: int | None = None, sender_rank: PrefixRank | None = None,
                                  sender_name: str | None = None, recipient_rank: PrefixRank | None = None,
                                  recipient_name: str | None = None):
        return await self.do_search_command(inter, {
           "itemId": "ANCIENT_ELEVATOR",
           "extraAttributes.edition": edition,
           "extraAttributes.sender": make_player_regex(sender_rank, sender_name) if sender_name or sender_rank else None,
           "extraAttributes.recipient_name": make_player_regex(recipient_rank, recipient_name) if recipient_name or recipient_rank else None,
       })

    @itemdb.sub_command(
        name="memento-search",
        description="Search the itemdb for a Memento"
    )
    async def memento_search_cmd(self, inter: disnake.AppCmdInter,
                                 memento: hypixel.Memento | None = None,
                                 edition: int | None = None, recipient_rank: PrefixRank | None = None,
                                 recipient_name: str | None = None, recipient_id: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": memento if memento else {"$in": hypixel.MEMENTOS},
            "extraAttributes.edition": edition,
            "extraAttributes.recipient_name": make_player_regex(recipient_rank, recipient_name) if recipient_name or recipient_rank else None,
            "extraAttributes.recipient_id": recipient_id
        })

    @itemdb.sub_command(
        name="racinghelm-search",
        description="Search the itemdb for a Racing Helmet"
    )
    async def racinghelm_search_cmd(self, inter: disnake.AppCmdInter,
                                    auction: int | None = None, bid: int | None = None,
                                    price: int | None = None, buyer_rank: PrefixRank | None = None,
                                    buyer_name: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": "RACING_HELMET",
            "extraAttributes.auction": auction,
            "extraAttributes.bid": bid,
            "extraAttributes.price": price,
            "extraAttributes.player": make_player_regex(buyer_rank, buyer_name) if buyer_name or buyer_rank else None
        })

    @itemdb.sub_command(
        name="spacehelm-search",
        description="Search the itemdb for a (Dctr) Space Helmet"
    )
    async def spacehelm_search_cmd(self, inter: disnake.AppCmdInter,
                                   edition: int | None = None, sender_rank: PrefixRank | None = None,
                                   sender_name: str | None = None, recipient_rank: PrefixRank | None = None,
                                   recipient_name: str | None = None):
        return await self.do_search_command(inter, {
            "itemId": "DCTR_SPACE_HELM",
            "extraAttributes.edition": edition,
            "extraAttributes.sender_name": make_player_regex(sender_rank, sender_name) if sender_name or sender_rank else None,
            "extraAttributes.recipient_name": make_player_regex(recipient_rank, recipient_name) if recipient_name or recipient_rank else None
        })

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        button_id = inter.component.custom_id
        if not button_id or not button_id.startswith("view_lore|"):
            return
        uuid = button_id.split('|')[1]
        item = await self.get_item_from_uuid(uuid)
        if not item:
            return await inter.send(embed=utils.make_error(
                "Item Not Found",
                "The item was not found in my databsae. This seems bad:bangbang:"
            ))
        lore = '\n'.join([utils.remove_color_codes(line) for line in item['lore']])
        return await inter.send(embed=disnake.Embed(
            title=utils.remove_color_codes(item.get('friendlyName', item['itemId'])),
            description=f"```\n{lore}```",
            color=constants.DEFAULT_EMBED_COLOR
        ), ephemeral=True)

    async def close(self):
        await self.item_db.close()
