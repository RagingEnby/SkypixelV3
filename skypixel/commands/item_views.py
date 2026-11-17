import asyncio
import logging
from typing import Any

import disnake
import pymongo

from skypixel import constants, utils
from skypixel.clients import mojang
from skypixel.commands.views import OwnedView
from skypixel.domain.items import fix_item, get_item_color, get_item_image
from skypixel.storage.mongo import Collection

logger = logging.getLogger(__name__)


def discord_time(milliseconds: Any, style: str = "d") -> str:
    """Format a millisecond timestamp, or show that it is unknown."""
    if isinstance(milliseconds, int) and milliseconds > 0:
        return f"<t:{milliseconds // 1000}:{style}>"
    return "unknown"


async def make_item_embed(item: dict[str, Any]) -> disnake.Embed:
    item = fix_item(item)
    previous_owners = list(reversed(item["previousOwners"]))[:5]
    try:
        players = await mojang.bulk(
            [item["currentOwner"]["playerUuid"]]
            + [po["owner"]["playerUuid"] for po in previous_owners]
        )
    except Exception:
        # The embed shows UUIDs for players it cannot name.
        logger.exception("Cannot load the owners of item %s.", item.get("_id"))
        players = {}

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
        url=constants.STATS_URL.format(item["currentOwner"]["playerUuid"]),
    )

    embed.add_field(
        name="UUID",
        value=f"{item['_id']}\n-# **Cofl UID:** {item.get('coflUid', 'unknown')}",
        inline=False,
    )

    embed.add_field(
        name="Current Owner",
        value=f"{utils.esc_mrkdwn(owner_name)} (since {discord_time(item.get('start'))})\n-# Item last seen {discord_time(item.get('lastChecked'))}",
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
                f"{player_name} ({discord_time(po.get('start'))} - {discord_time(po.get('end'))})"
            )
        embed.add_field(
            name="Previous Owner"
            if len(previous_owners) == 1
            else f"Previous {len(previous_owners)} Owners",
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

    if item.get("extraAttributes", {}).get("captured_date"):
        embed.add_field(
            name="Captured At",
            value=f"{discord_time(item['extraAttributes']['captured_date'])}\n-# {discord_time(item['extraAttributes']['captured_date'], 'R')}",
            inline=True,
        )

    if item.get("created_at"):
        embed.add_field(
            name="Creation Time",
            value=f"{discord_time(item['created_at'], 'f')}\n-# {discord_time(item['created_at'], 'R')}",
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
    cache_limit = 128

    def __init__(
        self,
        query: dict,
        count: int,
        main_embed: disnake.Embed,
        item_db: Collection,
        inter: disnake.Interaction,
    ):
        super().__init__(inter)
        self.query = query
        self.count = count
        self.main_embed = main_embed
        self.item_db = item_db
        self.index = 0
        self.item_cache: dict[int, dict] = {}
        self.embed_cache: dict[int, disnake.Embed] = {}
        self._page_lock = asyncio.Lock()
        self.update_buttons()

    async def get_current_item(self) -> dict | None:
        index = self.index
        if index in self.item_cache:
            return self.item_cache[index]
        cursor = self.item_db.find(self.query).sort(
            [
                ("extraAttributes.captured_date", pymongo.DESCENDING),
                ("_id", pymongo.ASCENDING),
            ]
        )
        cursor.skip(index).limit(1)
        try:
            item = await cursor.next()
            self.item_cache[index] = item
            while len(self.item_cache) > self.cache_limit:
                oldest = next(iter(self.item_cache))
                self.item_cache.pop(oldest)
                self.embed_cache.pop(oldest, None)
            return item
        except StopAsyncIteration:
            logger.info("Soul search results ended at item %s.", index)
            self.count = index
            self.index = max(index - 1, 0)
            self.update_buttons()
            return None

    async def get_current_embed(self) -> disnake.Embed | None:
        index = self.index
        if index in self.embed_cache:
            return self.embed_cache[index]
        item = await self.get_current_item()
        if not item:
            return None
        embed = await make_item_embed(item)
        embed.set_footer(text=f"Item {index + 1}/{self.count}")
        self.embed_cache[index] = embed
        return embed

    def update_buttons(self):
        self.previous.disabled = self.index <= 0
        self.next.disabled = self.index >= self.count - 1

    async def change_item(self, interaction: disnake.Interaction, offset: int) -> None:
        await interaction.response.defer()
        async with self._page_lock:
            self.index = max(0, min(self.index + offset, self.count - 1))
            embed = await self.get_current_embed()
            self.update_buttons()
            embeds = (
                [self.main_embed, embed] if embed is not None else [self.main_embed]
            )
            await interaction.edit_original_message(
                embeds=utils.fit_embeds(embeds), view=self
            )

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="⬅️", row=0)
    async def previous(
        self, button: disnake.ui.Button, interaction: disnake.Interaction
    ):
        await self.change_item(interaction, -1)

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="➡️", row=0)
    async def next(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        await self.change_item(interaction, 1)
