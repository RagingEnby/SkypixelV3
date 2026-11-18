import datetime
import logging
import random
import re
from contextlib import suppress
from copy import deepcopy
from urllib.parse import quote
from zoneinfo import ZoneInfo

import disnake

from skypixel import constants
from skypixel.clients import hypixel
from skypixel.storage.database import Alert

logger = logging.getLogger(__name__)
COLOR_CODE_PATTERN = re.compile(r"[§&][0-9a-fA-Fklmnor]")
# Minecraft format codes and their ansi escapes: bold, strikethrough, underline,
# italic, and reset. Obfuscated text (k) has no escape and becomes OBFUSCATED.
ANSI_FORMATS = {"l": 1, "m": 9, "n": 4, "o": 3, "r": 0}
OBFUSCATED = "\u2592"
# Old items carry their creation time as text in Hypixel's server time, which
# is US Eastern.
HYPIXEL_TIMEZONE = ZoneInfo("America/New_York")


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


async def respond(
    inter: disnake.Interaction, *, embed: disnake.Embed, ephemeral: bool = True
) -> None:
    embed = fit_embed(embed)
    if not inter.response.is_done():
        await inter.response.send_message(embed=embed, ephemeral=ephemeral)
        return
    if ephemeral:
        # The first followup replaces the public "thinking" message and is
        # public too. Delete that placeholder so this message can be private.
        with suppress(disnake.HTTPException):
            original = await inter.original_response()
            if original.flags.loading:
                await original.delete()
    await inter.followup.send(embed=embed, ephemeral=ephemeral)


async def send_error(inter: disnake.Interaction, title: str, *args) -> None:
    """Show an error to the user who ran the command, and to nobody else."""
    await respond(inter, embed=make_error(title, *args))


def remove_color_codes(string: str) -> str:
    return COLOR_CODE_PATTERN.sub("", string)


def to_ansi(string: str) -> str:
    """Turn Minecraft color codes into the escapes of a Discord ansi code block.

    Colors use 24-bit escapes with Minecraft's exact RGB values. Obfuscated
    text shows as a block character in place of each letter.
    """
    if not COLOR_CODE_PATTERN.search(string):
        return string
    parts = []
    obfuscated = False
    position = 0
    for match in COLOR_CODE_PATTERN.finditer(string):
        parts.append(_obfuscate(string[position : match.start()], obfuscated))
        position = match.end()
        code = match.group()[1].lower()
        if code in constants.COLOR_CODES:
            # A Minecraft color code also clears every format.
            obfuscated = False
            red, green, blue = constants.COLOR_CODES[code].to_bytes(3)
            parts.append(f"\u001b[0;38;2;{red};{green};{blue}m")
        elif code == "k":
            obfuscated = True
        else:
            obfuscated = obfuscated and code != "r"
            parts.append(f"\u001b[{ANSI_FORMATS[code]}m")
    parts.append(_obfuscate(string[position:], obfuscated))
    return "".join(parts) + "\u001b[0m"


def _obfuscate(text: str, obfuscated: bool) -> str:
    if not obfuscated:
        return text
    return "".join(char if char.isspace() else OBFUSCATED for char in text)


def ansi_block(lines: list[str]) -> str:
    """Return a code block that shows the lines with their Minecraft colors."""
    return "```ansi\n" + "\n".join(to_ansi(line) for line in lines) + "```"


def esc_mrkdwn(string: str) -> str:
    return disnake.utils.escape_markdown(string)


def add_footer(embed: disnake.Embed) -> disnake.Embed:
    return embed.set_footer(
        text=random.choice(sorted(constants.CREDIT_FOOTERS)),
        icon_url=constants.OWNER_PFP,
    )


async def send_to_channel(
    bot: disnake.Client,
    channel_id: int,
    *args,
    thread_id: int | None = None,
    **kwargs,
) -> disnake.Message | None:
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
    except disnake.HTTPException:
        logger.exception(
            "Cannot send to channel %s or thread %s.", channel_id, thread_id
        )
        return None


def broadcast(
    channels: dict[int, str],
    *,
    embed: disnake.Embed | None = None,
    embeds: list[disnake.Embed] | None = None,
    ping: bool = True,
) -> list[Alert]:
    """Return the alerts that send the embeds to each channel with its ping.

    A long embed list is split into messages of at most 10 embeds and 6000
    characters.
    """
    batches: list[list[disnake.Embed]] = []
    if embeds is None:
        batches.append([embed] if embed is not None else [])
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
    return [
        make_alert(channel_id, content if ping else "", embeds=batch)
        for batch in batches
        for channel_id, content in channels.items()
    ]


def make_alert(
    channel_id: int,
    content: str | None = None,
    *,
    thread_id: int | None = None,
    embed: disnake.Embed | None = None,
    embeds: list[disnake.Embed] | None = None,
) -> Alert:
    """Return an alert for a tracker to save with its state."""
    messages = embeds if embeds is not None else [embed] if embed is not None else []
    return Alert(
        channel_id,
        content,
        tuple(message.to_dict() for message in fit_embeds(messages)),
        thread_id,
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


def numerize(num: int | float) -> str:
    if abs(num) < 1000:
        return str(num)
    num = round(num)
    suffixes = ("", "K", "M", "B", "T")
    magnitude = 0
    while abs(num) >= 1000 and magnitude < len(suffixes) - 1:
        num /= 1000
        magnitude += 1
    # 999,999 becomes 999.999, which prints as 1000.00. Move it to the next suffix.
    if abs(round(num, 2)) >= 1000 and magnitude < len(suffixes) - 1:
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
            parsed = datetime.datetime.strptime(date_str, date_format)
            return int(parsed.replace(tzinfo=HYPIXEL_TIMEZONE).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Invalid timestamp: {date_str}")


def normalize_timestamp(timestamp: str | int) -> int:
    if isinstance(timestamp, str):
        timestamp = timestamp_to_unix(timestamp)
    return timestamp if abs(timestamp) < 100_000_000_000 else timestamp // 1000
