import json
import logging
from typing import Any, Literal

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import hypixel
from skypixel.commands.item_views import SoulSearchView, make_item_embed, make_item_view
from skypixel.domain.items import PrefixRank, make_player_regex, search_souls_query
from skypixel.storage.items import ItemRepository

logger = logging.getLogger(__name__)
Memento = Literal[tuple(hypixel.MEMENTOS)] if hypixel.MEMENTOS else str


class ItemDBCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.item_db = ItemRepository(bot.settings.mongodb_uri)
        self.bot = bot

    async def do_search_command(
        self, inter: disnake.AppCmdInter, query: dict[str, Any], limit: int = 1
    ):
        if not isinstance(query, dict):
            return await inter.send(
                embed=utils.make_error(
                    "Invalid Query", "Provide a JSON object or an item UUID."
                )
            )
        query = {k: v for k, v in query.items() if v is not None}
        if len(query) == 1 and query.get("itemId"):
            return await inter.send(
                embed=utils.make_error(
                    "Invalid Query", "You must provide search arguments!"
                )
            )
        logger.info("searching item db for: %s", json.dumps(query, indent=2))
        results = await self.item_db.search(query, limit=limit)
        if not results:
            return await inter.send(
                embed=utils.make_error(
                    "No Results Found",
                    "Your search yielded no items. Try broadening your search.",
                )
            )
        self.item_db.cache_items(results)
        embed = await make_item_embed(results[0])
        view = make_item_view(results[0])
        return await inter.send(embed=embed, view=view)

    @commands.slash_command(
        name="itemdb",
        description="Commands that use the RagingEnby item database",
        install_types=disnake.ApplicationInstallTypes.all(),
        contexts=disnake.InteractionContextTypes.all(),
    )
    async def itemdb(self, inter: disnake.AppCmdInter):
        await inter.response.defer()

    @itemdb.sub_command(
        name="search",
        description="**ADMIN ONLY** Search the item database using json params",
    )
    async def search(self, inter: disnake.AppCmdInter, query: str):
        if not await self.bot.is_owner(inter.author):
            return await inter.send(
                embed=utils.make_error(
                    "Not Owner", "You must be the bot owner to use this command!"
                )
            )
        try:
            parsed_query = json.loads(query)
        except json.JSONDecodeError:
            parsed_query = {"_id": query}
        return await self.do_search_command(inter, parsed_query)

    @itemdb.sub_command(
        name="soul-search",
        description="Searches the item database to see how many souls have been captured of a user",
    )
    async def soul_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        captured_rank: PrefixRank | None = None,
        captured_player: str | None = None,
        captured_by_rank: PrefixRank | None = None,
        captured_by_name: str | None = None,
        cake_owner_rank: PrefixRank | None = None,
        cake_owner_name: str | None = None,
    ):
        query = search_souls_query(
            {
                "itemId": "CAKE_SOUL",
                "extraAttributes.captured_player": make_player_regex(
                    captured_rank, captured_player
                )
                if captured_player or captured_rank
                else None,
                "extraAttributes.initiator_player": make_player_regex(
                    captured_by_rank, captured_by_name
                )
                if captured_by_name or captured_by_rank
                else None,
                "extraAttributes.cake_owner": make_player_regex(
                    cake_owner_rank, cake_owner_name
                )
                if cake_owner_name or cake_owner_rank
                else None,
            }
        )
        results = await self.item_db.search_souls(query)
        logger.info(json.dumps(results, indent=2))
        if not results:
            return await inter.send(
                embed=utils.make_error(
                    "No Results Found",
                    "No Cake Souls were found with this description.",
                )
            )
        embed = utils.add_footer(
            disnake.Embed(title="Soul Search Output", color=constants.COLOR_CODES["c"])
        )
        embed.set_thumbnail(utils.get_item_image("CAKE_SOUL"))
        for rank, count in results.items():
            embed.add_field(name=rank, value=count, inline=True)
        total = sum(results.values())
        if total > 1:
            view = SoulSearchView(
                query=query,
                count=total,
                main_embed=embed,
                item_db=self.item_db,
                inter=inter,
            )
            item_embed = await view.get_current_embed()
            await inter.send(
                embeds=utils.fit_embeds(
                    [i for i in [embed, item_embed] if i is not None]
                ),
                view=view,
            )
        else:
            result = await self.item_db.find_one(query)
            embeds = [embed]
            if result is not None:
                embeds.append(await make_item_embed(result))
            await inter.send(embeds=utils.fit_embeds(embeds))

    @itemdb.sub_command(
        name="clay-search", description="Search the itemdb for a Builder's Clay"
    )
    async def clay_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        edition: int | None = None,
        sender_rank: PrefixRank | None = None,
        sender_name: str | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
    ):
        return await self.do_search_command(
            inter,
            {
                "itemId": "DUECES_BUILDER_CLAY",
                "extraAttributes.edition": edition,
                "extraAttributes.sender": make_player_regex(sender_rank, sender_name)
                if sender_name or sender_rank
                else None,
                "extraAttributes.recipient_name": make_player_regex(
                    recipient_rank, recipient_name
                )
                if recipient_name or recipient_rank
                else None,
            },
        )

    @itemdb.sub_command(
        name="basket-search", description="Search the itemdb for a Basket of Hope"
    )
    async def basket_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        edition: int | None = None,
        basket_player_rank: PrefixRank | None = None,
        basket_player_name: str | None = None,
    ):
        return await self.do_search_command(
            inter,
            {
                "itemId": "POTATO_BASKET",
                "extraAttributes.basket_edition": edition,
                "extraAttributes.basket_player_name": make_player_regex(
                    basket_player_rank, basket_player_name
                )
                if basket_player_name or basket_player_rank
                else None,
            },
        )

    @itemdb.sub_command(
        name="elevator-search", description="Search the itemdb for an Ancient Elevator"
    )
    async def elevator_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        edition: int | None = None,
        sender_rank: PrefixRank | None = None,
        sender_name: str | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
    ):
        return await self.do_search_command(
            inter,
            {
                "itemId": "ANCIENT_ELEVATOR",
                "extraAttributes.edition": edition,
                "extraAttributes.sender": make_player_regex(sender_rank, sender_name)
                if sender_name or sender_rank
                else None,
                "extraAttributes.recipient_name": make_player_regex(
                    recipient_rank, recipient_name
                )
                if recipient_name or recipient_rank
                else None,
            },
        )

    @itemdb.sub_command(
        name="memento-search", description="Search the itemdb for a Memento"
    )
    async def memento_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        memento: Memento | None = None,
        edition: int | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
        recipient_id: str | None = None,
    ):
        return await self.do_search_command(
            inter,
            {
                "itemId": memento if memento else {"$in": hypixel.MEMENTOS},
                "extraAttributes.edition": edition,
                "extraAttributes.recipient_name": make_player_regex(
                    recipient_rank, recipient_name
                )
                if recipient_name or recipient_rank
                else None,
                "extraAttributes.recipient_id": recipient_id,
            },
        )

    @itemdb.sub_command(
        name="racinghelm-search", description="Search the itemdb for a Racing Helmet"
    )
    async def racinghelm_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        auction: int | None = None,
        bid: int | None = None,
        price: int | None = None,
        buyer_rank: PrefixRank | None = None,
        buyer_name: str | None = None,
    ):
        return await self.do_search_command(
            inter,
            {
                "itemId": "RACING_HELMET",
                "extraAttributes.auction": auction,
                "extraAttributes.bid": bid,
                "extraAttributes.price": price,
                "extraAttributes.player": make_player_regex(buyer_rank, buyer_name)
                if buyer_name or buyer_rank
                else None,
            },
        )

    @itemdb.sub_command(
        name="spacehelm-search",
        description="Search the itemdb for a (Dctr) Space Helmet",
    )
    async def spacehelm_search_cmd(
        self,
        inter: disnake.AppCmdInter,
        edition: int | None = None,
        sender_rank: PrefixRank | None = None,
        sender_name: str | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
    ):
        return await self.do_search_command(
            inter,
            {
                "itemId": "DCTR_SPACE_HELM",
                "extraAttributes.edition": edition,
                "extraAttributes.sender_name": make_player_regex(
                    sender_rank, sender_name
                )
                if sender_name or sender_rank
                else None,
                "extraAttributes.recipient_name": make_player_regex(
                    recipient_rank, recipient_name
                )
                if recipient_name or recipient_rank
                else None,
            },
        )

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        button_id = inter.component.custom_id
        if not button_id or not button_id.startswith("view_lore|"):
            return
        await inter.response.defer(ephemeral=True, with_message=True)
        uuid = button_id.partition("|")[2]
        item = await self.item_db.get_item(uuid)
        if not item:
            return await inter.send(
                embed=utils.make_error(
                    "Item Not Found",
                    "This item is no longer in the database.",
                ),
                ephemeral=True,
            )
        lore = "\n".join(
            utils.remove_color_codes(line) for line in item.get("lore", [])
        )
        return await inter.send(
            embed=utils.fit_embed(
                disnake.Embed(
                    title=utils.remove_color_codes(
                        item.get("friendlyName", item["itemId"])
                    ),
                    description=f"```\n{lore}```",
                    color=constants.DEFAULT_EMBED_COLOR,
                )
            ),
            ephemeral=True,
        )

    async def close(self):
        await self.item_db.close()
