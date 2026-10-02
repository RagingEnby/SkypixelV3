import logging
from typing import Any

import disnake
import pymongo

from skypixel import discord as utils
from skypixel.clients import mojang
from skypixel.commands.views import OwnedView
from skypixel.domain.items import fix_item, get_item_color, get_item_image
from skypixel.storage import mongo as mongodb

logger = logging.getLogger(__name__)


async def make_item_embed(item: dict[str, Any]) -> disnake.Embed:
    item = fix_item(item)
    previous_owners = list(reversed(item["previousOwners"]))[:5]
    players = await mojang.bulk(
        [item["currentOwner"]["playerUuid"]]
        + [po["owner"]["playerUuid"] for po in previous_owners]
    )

    embed = utils.add_footer(
        disnake.Embed(
            title=utils.remove_color_codes(item.get("friendlyName", item["itemId"])),
            color=get_item_color(item),
        )
    )
    embed.set_thumbnail(url=get_item_image(item))

    owner = players.get(item["currentOwner"]["playerUuid"])
    owner_name = owner.name if owner else item["currentOwner"]["playerUuid"]
    embed.set_author(
        name=owner_name,
        icon_url=owner.avatar if owner else None,
        url="https://sky.shiiyu.moe/stats/" + item["currentOwner"]["playerUuid"],
    )

    embed.add_field(
        name="UUID",
        value=f"{item['_id']}\n-# **Cofl UID:** {item['coflUid']}",
        inline=False,
    )

    embed.add_field(
        name="Current Owner",
        value=f"{utils.esc_mrkdwn(owner_name)} (since <t:{item['start'] // 1000}:d>)\n-# Item last seen <t:{item['lastChecked'] // 1000}:d>",
        inline=False,
    )

    if previous_owners:
        lines = []
        for po in previous_owners:
            player = players.get(po["owner"]["playerUuid"])
            player_name = (
                utils.esc_mrkdwn(player.name) if player else po["owner"]["playerUuid"]
            )
            lines.append(
                f"{player_name} (<t:{po['start'] // 1000}:d> - <t:{po['end'] // 1000}:d>)"
            )
        embed.add_field(
            name=f"Previous {len(previous_owners)} Owners",
            value="\n".join(lines),
            inline=False,
        )

    if item.get("extraAttributes"):
        extra_attributes_text = "\n".join(
            [f"{k}: {v}" for k, v in item["extraAttributes"].items()]
        )
        embed.add_field(
            name="Extra Attributes",
            value=f"```\n{extra_attributes_text}```",
            inline=True,
        )

    if item.get("enchantments"):
        enchantments_text = "\n".join(
            [f"{k}: {v}" for k, v in item["enchantments"].items()]
        )
        embed.add_field(
            name="Enchantments", value=f"```\n{enchantments_text}```", inline=True
        )

    if item.get("attributes"):
        attributes_text = "\n".join(
            [f"{k}: {v}" for k, v in item["attributes"].items()]
        )
        embed.add_field(
            name="Attributes", value=f"```\n{attributes_text}```", inline=False
        )
    else:
        embed.add_field(name="", value=" ", inline=False)

    if item["extraAttributes"].get("captured_date"):
        embed.add_field(
            name="Captured At",
            value=f"<t:{item['extraAttributes']['captured_date'] // 1000}:d>\n-# <t:{item['extraAttributes']['captured_date'] // 1000}:R>",
            inline=True,
        )

    if item.get("created_at"):
        embed.add_field(
            name="Creation Time",
            value=f"<t:{item['created_at'] // 1000}:f>\n-# <t:{item['created_at'] // 1000}:R>",
            inline=True,
        )

    if item.get("rarity"):
        embed.add_field(name="Rarity", value=item["rarity"], inline=True)

    if item.get("soulbound"):
        embed.add_field(name="Soulbound", value=item["soulbound"], inline=True)

    if item.get("reforge"):
        embed.add_field(name="Reforge", value=item["reforge"], inline=True)

    if item.get("colour"):
        exotic_text = f" ({item['exoticType']})" if item.get("exoticType") else ""
        embed.add_field(
            name="Color", value="#" + item["colour"] + exotic_text, inline=True
        )

    if item.get("location"):
        embed.add_field(name="Location", value=item["location"], inline=True)
    return utils.fit_embed(embed)


def make_item_view(item: dict[str, Any]) -> disnake.ui.View:
    view = disnake.ui.View()
    view.add_item(
        disnake.ui.Button(
            label="View Raw Data",
            url="https://api.ragingenby.dev/items/" + item["_id"],
            style=disnake.ButtonStyle.link,
        )
    )
    if item.get("lore"):
        view.add_item(
            disnake.ui.Button(
                label="View Lore",
                style=disnake.ButtonStyle.primary,
                custom_id="view_lore|" + item["_id"],
            )
        )
    return view


class SoulSearchView(OwnedView):
    def __init__(
        self,
        query: dict,
        count: int,
        main_embed: disnake.Embed,
        item_db: mongodb.Collection,
        inter: disnake.Interaction,
    ):
        super().__init__(inter)
        self.query = query
        self.count = count
        self.main_embed = main_embed
        self.item_db = item_db
        self.inter = inter
        self.index = 0
        self.item_cache: dict[int, dict] = {}
        self.embed_cache: dict[int, disnake.Embed] = {}

    async def get_current_item(self) -> dict | None:
        if self.item_cache.get(self.index):
            return self.item_cache[self.index]
        cursor = self.item_db.find(self.query).sort(
            [("extraAttributes.captured_date", pymongo.DESCENDING)]
        )
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
        embed.set_footer(text=f"Item {self.index + 1}/{self.count}")
        self.embed_cache[self.index] = embed
        return embed

    async def update_buttons(self):
        logger.debug("updating buttons")
        self.children[0].disabled = self.index == 0  # type: ignore[index]
        self.children[1].disabled = self.index == self.count - 1  # type: ignore[index]

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="⬅️", row=0)
    async def previous(
        self, button: disnake.ui.Button, interaction: disnake.Interaction
    ):
        logger.debug("previous button clicked")
        self.index = max(self.index - 1, 0)
        await self.update_buttons()
        embed = await self.get_current_embed()
        if not embed:
            return await interaction.response.edit_message(
                embeds=[self.main_embed], view=self
            )
        await interaction.response.edit_message(
            embeds=utils.fit_embeds([self.main_embed, embed]), view=self
        )

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="➡️", row=0)
    async def next(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        logger.debug("next button clicked")
        self.index = min(self.index + 1, max(self.count - 1, 0))
        await self.update_buttons()
        embed = await self.get_current_embed()
        if not embed:
            return await interaction.response.edit_message(
                embeds=[self.main_embed], view=self
            )
        await interaction.response.edit_message(
            embeds=utils.fit_embeds([self.main_embed, embed]), view=self
        )
