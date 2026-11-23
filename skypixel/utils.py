import asyncio
import datetime
import logging
import random
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import disnake

from skypixel import constants
from skypixel.clients import hypixel
from skypixel.storage.notifications import notification_fingerprint

logger = logging.getLogger(__name__)
COLOR_CODE_PATTERN = re.compile(r"[§&][0-9a-fA-Fklmnor]")


def make_error(title: str, *args) -> disnake.Embed:
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
            name=field.name[:256],
            value=truncate(field.value, 1024),
            inline=field.inline,
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
        if len(field.value) > excess:
            embed.set_field_at(
                index,
                name=field.name,
                value=truncate(field.value, len(field.value) - excess),
                inline=field.inline,
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


async def respond(
    inter: disnake.Interaction, *, embed: disnake.Embed, ephemeral: bool = True
) -> None:
    if inter.response.is_done():
        await inter.followup.send(embed=fit_embed(embed), ephemeral=ephemeral)
    else:
        await inter.response.send_message(embed=fit_embed(embed), ephemeral=ephemeral)


def remove_color_codes(string: str) -> str:
    return COLOR_CODE_PATTERN.sub("", string)


def esc_mrkdwn(string: str) -> str:
    return disnake.utils.escape_markdown(string)


def add_footer(embed: disnake.Embed) -> disnake.Embed:
    return embed.set_footer(
        text=random.choice(sorted(constants.CREDIT_FOOTERS)),
        icon_url=constants.OWNER_PFP,
    )


def is_discord_muted(bot: disnake.Client) -> bool:
    settings = getattr(bot, "settings", None)
    storage_dir = getattr(settings, "storage_dir", None)
    if not isinstance(storage_dir, Path):
        return False
    return (storage_dir / "muted").exists()


class PermanentDeliveryError(Exception):
    """Raised when Discord permanently rejects a channel send."""


def _is_external_guild(target: disnake.abc.Messageable) -> bool:
    guild = getattr(target, "guild", None)
    guild_id = getattr(guild, "id", None)
    return isinstance(guild_id, int) and guild_id != constants.DEV_SERVER_ID


async def send_to_channel(
    bot: disnake.Client,
    channel_id: int,
    *args,
    thread_id: int | None = None,
    raise_permanent: bool = False,
    **kwargs,
) -> disnake.Message | None:
    if is_discord_muted(bot):
        logger.warning(
            "Discord output is muted; suppressed message to channel %s (thread %s).",
            channel_id,
            thread_id,
        )
        return None
    channel = bot.get_channel(channel_id)
    if thread_id is not None:
        if not isinstance(channel, (disnake.TextChannel, disnake.ForumChannel)):
            logger.warning("Cannot find the parent channel %s.", channel_id)
            return None
        target = channel.get_thread(thread_id)
    else:
        target = channel if isinstance(channel, disnake.TextChannel) else None
    if target is None:
        logger.warning("Cannot find channel %s or thread %s.", channel_id, thread_id)
        return None
    if embed := kwargs.get("embed"):
        fit_embed(embed)
    if "embeds" in kwargs:
        kwargs["embeds"] = fit_embeds(kwargs["embeds"])
    try:
        return await target.send(*args, **kwargs)
    except (disnake.Forbidden, disnake.NotFound) as error:
        if _is_external_guild(target):
            logger.warning(
                "Cannot send to external channel %s or thread %s: %s",
                channel_id,
                thread_id,
                error,
            )
        else:
            logger.exception(
                "Cannot send to channel %s or thread %s.", channel_id, thread_id
            )
        if raise_permanent:
            raise PermanentDeliveryError(str(error)) from error
        return None
    except disnake.HTTPException:
        logger.exception(
            "Cannot send to channel %s or thread %s.", channel_id, thread_id
        )
        return None


async def broadcast(
    bot: disnake.Client,
    channels: dict[int, str],
    *,
    embed: disnake.Embed | None = None,
    embeds: list[disnake.Embed] | None = None,
    ping: bool = True,
) -> None:
    batches = []
    if embeds is None:
        batches.append(None)
    else:
        batch, length = [], 0
        for candidate in embeds:
            fit_embed(candidate)
            if batch and (len(batch) == 10 or length + len(candidate) > 6000):
                batches.append(batch)
                batch, length = [], 0
            batch.append(candidate)
            length += len(candidate)
        if batch:
            batches.append(batch)
    version = notification_fingerprint(
        {
            "channels": channels,
            "ping": ping,
            "embeds": [
                message.to_dict()
                for message in (
                    embeds
                    if embeds is not None
                    else [embed]
                    if embed is not None
                    else []
                )
            ],
        }
    )
    async with bot.notifications.event("broadcast", version):
        for batch in batches:
            kwargs = {"embeds": batch} if batch is not None else {"embed": embed}
            results = await asyncio.gather(
                *(
                    notify_to_channel(
                        bot, channel_id, content if ping else "", **kwargs
                    )
                    for channel_id, content in channels.items()
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result


async def notify_to_channel(
    bot: disnake.Client,
    channel_id: int,
    content: str | None = None,
    **kwargs,
) -> disnake.Message | None:
    return await bot.notifications.submit(channel_id, content, **kwargs)


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


def numerize(num: int | float) -> str:
    if num < 1000:
        return str(num)
    num = round(num)
    suffixes = ("", "K", "M", "B", "T")
    magnitude = 0
    while abs(num) >= 1000 and magnitude < len(suffixes) - 1:
        num /= 1000
        magnitude += 1
    return f"{num:.2f}".rstrip("0").rstrip(".") + suffixes[magnitude]


def commaize(num: int | float) -> str:
    return f"{num:,}"


def timestamp_to_unix(date_str: str) -> int:
    if "L" in date_str:
        return int(date_str.replace("L", ""))
    try:
        return int(date_str)
    except ValueError:
        pass
    for date_format in ("%m/%d/%y %I:%M %p", "%d/%m/%y %H:%M"):
        try:
            return int(datetime.datetime.strptime(date_str, date_format).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Invalid timestamp: {date_str}")


def normalize_timestamp(timestamp: str | int) -> int:
    if isinstance(timestamp, str):
        timestamp = timestamp_to_unix(timestamp)
    return timestamp if abs(timestamp) < 100_000_000_000 else timestamp // 1000
