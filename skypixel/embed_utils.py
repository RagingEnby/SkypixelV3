"""Build and trim Discord embeds."""

import logging
import random
from copy import deepcopy
from urllib.parse import quote

import disnake

from skypixel import constants
from skypixel.clients import hypixel

logger: logging.Logger = logging.getLogger(__name__)


def make_error(title: str, *args: object) -> disnake.Embed:
    return fit_embed(
        add_footer(
            disnake.Embed(
                title=title,
                description="\n".join(map(str, args)),
                color=constants.COLOR_CODES["c"],
            )
        )
    )


def truncate(text: str, limit: int) -> str:
    """Cut text to the limit and close a code block that the cut left open."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if cut.count("```") % 2 == 0:
        return cut
    cut = text[: max(0, limit - 4)]
    if cut.count("```") % 2:
        return cut + "\u2026```"
    return cut.rstrip("`")


def fit_embed(embed: disnake.Embed, max_length: int = 6000) -> disnake.Embed:
    if embed.title:
        embed.title = embed.title[:256]
    if embed.description:
        embed.description = truncate(embed.description, 4096)
    for index, field in enumerate(embed.fields):
        if index >= 25:
            embed.remove_field(25)
            continue
        embed.set_field_at(
            index,
            name=(field.name or "")[:256],
            value=truncate(field.value or "", 1024),
            inline=bool(field.inline),
        )
    if embed.author.name:
        embed.set_author(
            name=embed.author.name[:256],
            url=embed.author.url,
            icon_url=embed.author.icon_url,
        )
    if embed.footer.text:
        embed.set_footer(text=embed.footer.text[:2048], icon_url=embed.footer.icon_url)
    for index in reversed(range(len(embed.fields))):
        excess = len(embed) - max_length
        if excess <= 0:
            break
        field = embed.fields[index]
        value = field.value or ""
        if len(value) > excess:
            embed.set_field_at(
                index,
                name=field.name,
                value=truncate(value, len(value) - excess),
                inline=bool(field.inline),
            )
        else:
            embed.remove_field(index)
    if len(embed) > max_length and embed.description:
        embed.description = (
            truncate(
                embed.description,
                max(0, len(embed.description) - (len(embed) - max_length)),
            )
            or None
        )
    if len(embed) > max_length and embed.footer.text:
        text = embed.footer.text[
            : max(0, len(embed.footer.text) - (len(embed) - max_length))
        ]
        if text:
            embed.set_footer(text=text, icon_url=embed.footer.icon_url)
        else:
            embed.remove_footer()
    if len(embed) > max_length and embed.author.name:
        name = embed.author.name[
            : max(0, len(embed.author.name) - (len(embed) - max_length))
        ]
        if name:
            embed.set_author(
                name=name, url=embed.author.url, icon_url=embed.author.icon_url
            )
        else:
            embed.remove_author()
    if len(embed) > max_length and embed.title:
        embed.title = (
            embed.title[: max(0, len(embed.title) - (len(embed) - max_length))] or None
        )
    return embed


def fit_embeds(embeds: list[disnake.Embed]) -> list[disnake.Embed]:
    copies = [
        fit_embed(disnake.Embed.from_dict(deepcopy(embed.to_dict())))
        for embed in embeds[:10]
    ]
    total = sum(map(len, copies))
    if total > 6000:
        for embed in copies:
            budget = 1 + (6000 - len(copies)) * len(embed) // total
            fit_embed(embed, max_length=budget)
    return copies


def add_footer(embed: disnake.Embed) -> disnake.Embed:
    return embed.set_footer(
        text=random.choice(sorted(constants.CREDIT_FOOTERS)),
        icon_url=constants.OWNER_PFP,
    )


def to_mc_text(text: str) -> str:
    return constants.MC_TEXT_IMAGE.format(quote(text))


def get_item_image(
    item_id: str, color: str | None = None, durability: int | None = None
) -> str:
    if item_id == "CAKE_SOUL" and durability in constants.MINECRAFT_DYES:
        return constants.MINECRAFT_DYES[durability]["image"]
    default = constants.ITEM_IMAGE.format(item_id)
    if not color:
        return default
    try:
        material = hypixel.get_material(item_id)
    except (KeyError, ValueError):  # fmt: skip
        logger.debug("Cannot find a material for item %s.", item_id)
        return default
    if not material.startswith("LEATHER_"):
        return default
    return constants.LEATHER_IMAGE.format(
        material.removeprefix("LEATHER_").lower(), color
    )
