import json
import logging
from itertools import islice
from typing import TYPE_CHECKING

import disnake
from disnake.ext import commands

from skypixel import constants, delivery, embed_utils, formatting
from skypixel.clients import hypixel
from skypixel.commands.item_views import SoulSearchView, make_item_embed, make_item_view
from skypixel.domain.items import PrefixRank, player_filter, search_souls_query
from skypixel.domain.types import JSON, Document
from skypixel.storage.items import ItemRepository

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger: logging.Logger = logging.getLogger(__name__)


def memento_name(item_id: str) -> str:
    try:
        return hypixel.get_name(item_id)
    except (KeyError, ValueError):  # fmt: skip
        return item_id


async def autocomplete_memento(
    _inter: disnake.AppCmdInter[disnake.Client], text: str
) -> dict[str, str]:
    """Offer up to 25 mementos whose name or ID contains the typed text."""
    text = text.lower()
    matches = (
        item_id
        for item_id in hypixel.MEMENTOS
        if text in memento_name(item_id).lower() or text in item_id.lower()
    )
    return {memento_name(item_id)[:100]: item_id for item_id in islice(matches, 25)}


def find_memento(text: str) -> str | None:
    """Match typed text to a memento ID or name, for users who skip the list."""
    for item_id in hypixel.MEMENTOS:
        if text.lower() in (item_id.lower(), memento_name(item_id).lower()):
            return item_id
    return None


def gift_query(
    item_id: str,
    sender_field: str,
    edition: int | None,
    sender_rank: PrefixRank | None,
    sender_name: str | None,
    recipient_rank: PrefixRank | None,
    recipient_name: str | None,
) -> dict[str, Any]:
    """Build the query for an edition item sent from one player to another."""
    return {
        "itemId": item_id,
        "extraAttributes.edition": edition,
        sender_field: player_filter(sender_rank, sender_name),
        "extraAttributes.recipient_name": player_filter(recipient_rank, recipient_name),
    }


class ItemDBCog(commands.Cog):
    def __init__(self, bot: SkypixelBot) -> None:
        self.item_db: ItemRepository = bot.services.item_db
        self.bot: SkypixelBot = bot

    async def do_search_command(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        query: JSON | Document,
        limit: int = 1,
    ) -> None:
        # The owner's search command passes parsed JSON, which can be any type.
        if not isinstance(query, dict):
            return await delivery.send_error(
                inter, "Invalid Query", "Provide a JSON object or an item UUID."
            )
        search_query: Document = {k: v for k, v in query.items() if v is not None}
        if len(search_query) == 1 and search_query.get("itemId"):
            return await delivery.send_error(
                inter, "Invalid Query", "You must provide search arguments!"
            )
        logger.info("searching item db for: %s", json.dumps(search_query, indent=2))
        results = await self.item_db.search(search_query, limit=limit)
        if not results:
            return await inter.send(
                embed=embed_utils.make_error(
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
    async def itemdb(self, inter: disnake.AppCmdInter[disnake.Client]) -> None:
        await inter.response.defer()

    @itemdb.sub_command(
        name="search",
        description="Owner only. Search the item database with a JSON query",
    )
    async def search(
        self, inter: disnake.AppCmdInter[disnake.Client], query: str
    ) -> None:
        """
        Parameters
        ----------
        query: A JSON query or an item UUID
        """
        if not await self.bot.is_owner(inter.author):
            return await delivery.send_error(
                inter, "Not Owner", "You must be the bot owner to use this command!"
            )
        try:
            parsed_query: JSON = json.loads(query)
        except json.JSONDecodeError:
            parsed_query = {"_id": query}
        return await self.do_search_command(inter, parsed_query)

    @itemdb.sub_command(
        name="soul-search",
        description="Count the Cake Souls that match a captured player, a capturer, or a cake owner",
    )
    async def soul_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        captured_rank: PrefixRank | None = None,
        captured_player: str | None = None,
        captured_by_rank: PrefixRank | None = None,
        captured_by_name: str | None = None,
        cake_owner_rank: PrefixRank | None = None,
        cake_owner_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        captured_rank: Rank of the captured player
        captured_player: Name of the captured player
        captured_by_rank: Rank of the player who captured the soul
        captured_by_name: Name of the player who captured the soul
        cake_owner_rank: Rank of the cake's owner
        cake_owner_name: Name of the cake's owner
        """
        query = search_souls_query(
            {
                "itemId": "CAKE_SOUL",
                "extraAttributes.captured_player": player_filter(
                    captured_rank, captured_player
                ),
                "extraAttributes.initiator_player": player_filter(
                    captured_by_rank, captured_by_name
                ),
                "extraAttributes.cake_owner": player_filter(
                    cake_owner_rank, cake_owner_name
                ),
            }
        )
        results = await self.item_db.search_souls(query)
        logger.info(json.dumps(results, indent=2))
        if not results:
            return await inter.send(
                embed=embed_utils.make_error(
                    "No Results Found",
                    "No Cake Souls were found with this description.",
                )
            )
        embed = embed_utils.add_footer(
            disnake.Embed(
                title="Soul Search Output", color=constants.DEFAULT_EMBED_COLOR
            )
        )
        embed.set_thumbnail(embed_utils.get_item_image("CAKE_SOUL"))
        # Show the most common rank first.
        for rank, count in sorted(
            results.items(), key=lambda result: result[1], reverse=True
        ):
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
                embeds=embed_utils.fit_embeds(
                    [i for i in [embed, item_embed] if i is not None]
                ),
                view=view,
            )
        else:
            result = await self.item_db.find_one(query)
            embeds = [embed]
            if result is not None:
                embeds.append(await make_item_embed(result))
            await inter.send(embeds=embed_utils.fit_embeds(embeds))

    @itemdb.sub_command(
        name="clay-search", description="Search the itemdb for a Builder's Clay"
    )
    async def clay_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        edition: int | None = None,
        sender_rank: PrefixRank | None = None,
        sender_name: str | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        edition: Edition number
        sender_rank: Rank of the sender
        sender_name: Name of the sender
        recipient_rank: Rank of the recipient
        recipient_name: Name of the recipient
        """
        return await self.do_search_command(
            inter,
            gift_query(
                "DUECES_BUILDER_CLAY",
                "extraAttributes.sender",
                edition,
                sender_rank,
                sender_name,
                recipient_rank,
                recipient_name,
            ),
        )

    @itemdb.sub_command(
        name="basket-search", description="Search the itemdb for a Basket of Hope"
    )
    async def basket_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        edition: int | None = None,
        basket_player_rank: PrefixRank | None = None,
        basket_player_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        edition: Edition number
        basket_player_rank: Rank of the basket's player
        basket_player_name: Name of the basket's player
        """
        return await self.do_search_command(
            inter,
            {
                "itemId": "POTATO_BASKET",
                "extraAttributes.basket_edition": edition,
                "extraAttributes.basket_player_name": player_filter(
                    basket_player_rank, basket_player_name
                ),
            },
        )

    @itemdb.sub_command(
        name="elevator-search", description="Search the itemdb for an Ancient Elevator"
    )
    async def elevator_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        edition: int | None = None,
        sender_rank: PrefixRank | None = None,
        sender_name: str | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        edition: Edition number
        sender_rank: Rank of the sender
        sender_name: Name of the sender
        recipient_rank: Rank of the recipient
        recipient_name: Name of the recipient
        """
        return await self.do_search_command(
            inter,
            gift_query(
                "ANCIENT_ELEVATOR",
                "extraAttributes.sender",
                edition,
                sender_rank,
                sender_name,
                recipient_rank,
                recipient_name,
            ),
        )

    @itemdb.sub_command(
        name="memento-search", description="Search the itemdb for a Memento"
    )
    async def memento_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        # disnake types the autocomplete callback with no client type.
        memento: str | None = commands.Param(  # pyright: ignore[reportUnknownMemberType]
            default=None, autocomplete=autocomplete_memento
        ),
        edition: int | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        memento: The memento to search for
        edition: Edition number
        recipient_rank: Rank of the recipient
        recipient_name: Name of the recipient
        recipient_id: UUID of the recipient
        """
        item_id = find_memento(memento) if memento else None
        if memento and item_id is None:
            return await delivery.send_error(
                inter, "Unknown Memento", "Pick a memento from the list."
            )
        return await self.do_search_command(
            inter,
            {
                "itemId": item_id or {"$in": hypixel.MEMENTOS},
                "extraAttributes.edition": edition,
                "extraAttributes.recipient_name": player_filter(
                    recipient_rank, recipient_name
                ),
                "extraAttributes.recipient_id": recipient_id,
            },
        )

    @itemdb.sub_command(
        name="racinghelm-search", description="Search the itemdb for a Racing Helmet"
    )
    async def racinghelm_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        auction: int | None = None,
        bid: int | None = None,
        price: int | None = None,
        buyer_rank: PrefixRank | None = None,
        buyer_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        auction: Auction number
        bid: Bid number
        price: Winning price in coins
        buyer_rank: Rank of the buyer
        buyer_name: Name of the buyer
        """
        return await self.do_search_command(
            inter,
            {
                "itemId": "RACING_HELMET",
                "extraAttributes.auction": auction,
                "extraAttributes.bid": bid,
                "extraAttributes.price": price,
                "extraAttributes.player": player_filter(buyer_rank, buyer_name),
            },
        )

    @itemdb.sub_command(
        name="spacehelm-search",
        description="Search the itemdb for a (Dctr) Space Helmet",
    )
    async def spacehelm_search_cmd(
        self,
        inter: disnake.AppCmdInter[disnake.Client],
        edition: int | None = None,
        sender_rank: PrefixRank | None = None,
        sender_name: str | None = None,
        recipient_rank: PrefixRank | None = None,
        recipient_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        edition: Edition number
        sender_rank: Rank of the sender
        sender_name: Name of the sender
        recipient_rank: Rank of the recipient
        recipient_name: Name of the recipient
        """
        return await self.do_search_command(
            inter,
            gift_query(
                "DCTR_SPACE_HELM",
                "extraAttributes.sender_name",
                edition,
                sender_rank,
                sender_name,
                recipient_rank,
                recipient_name,
            ),
        )

    @commands.Cog.listener()
    async def on_button_click(
        self, inter: disnake.MessageInteraction[disnake.Client]
    ) -> None:
        button_id = inter.component.custom_id
        if not button_id or not button_id.startswith("view_lore|"):
            return
        await inter.response.defer(ephemeral=True, with_message=True)
        uuid = button_id.partition("|")[2]
        item = await self.item_db.get_item(uuid)
        if not item:
            return await inter.send(
                embed=embed_utils.make_error(
                    "Item Not Found",
                    "This item is no longer in the database.",
                ),
                ephemeral=True,
            )
        lore = "\n".join(
            formatting.remove_color_codes(line) for line in item.get("lore", [])
        )
        return await inter.send(
            embed=embed_utils.fit_embed(
                disnake.Embed(
                    title=formatting.remove_color_codes(
                        item.get("friendlyName", item["itemId"])
                    ),
                    description=f"```\n{lore}```",
                    color=constants.DEFAULT_EMBED_COLOR,
                )
            ),
            ephemeral=True,
        )
