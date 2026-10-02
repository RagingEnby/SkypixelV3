import datetime
import logging
import random
import re
from urllib.parse import quote

import disnake

from skypixel import constants
from skypixel.clients import hypixel
from skypixel.storage.json import write_json

logger = logging.getLogger(__name__)
COLOR_CODE_PATTERN = re.compile(r"[§&][0-9a-fA-Fklmnor]")


def make_error(title: str, *args) -> disnake.Embed:
    return add_footer(
        disnake.Embed(
            title=title,
            description="\n".join(map(str, args)),
            color=constants.COLOR_CODES["c"],
        )
    )


def remove_color_codes(string: str) -> str:
    return COLOR_CODE_PATTERN.sub("", string)


def esc_mrkdwn(string: str) -> str:
    return disnake.utils.escape_markdown(string)


def add_footer(embed: disnake.Embed) -> disnake.Embed:
    return embed.set_footer(
        text=random.choice(sorted(constants.CREDIT_FOOTERS)),
        icon_url=constants.OWNER_PFP,
    )


async def send_to_channel(
    channel_id: int, *args, thread_id: int | None = None, **kwargs
) -> disnake.Message | None:
    bot = constants.BOT
    if bot is None:
        logger.warning("Cannot send to channel %s before the bot starts.", channel_id)
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
    try:
        return await target.send(*args, **kwargs)
    except disnake.HTTPException:
        logger.exception(
            "Cannot send to channel %s or thread %s.", channel_id, thread_id
        )
        return None


async def broadcast(
    channels: dict[int, str],
    *,
    embed: disnake.Embed | None = None,
    embeds: list[disnake.Embed] | None = None,
    ping: bool = True,
) -> None:
    import asyncio

    batches = (
        [embeds[index : index + 10] for index in range(0, len(embeds), 10)]
        if embeds is not None
        else [None]
    )
    for batch in batches:
        kwargs = {"embeds": batch} if batch is not None else {"embed": embed}
        await asyncio.gather(
            *(
                send_to_channel(channel_id, content if ping else "", **kwargs)
                for channel_id, content in channels.items()
            )
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
    except (KeyError, ValueError):
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
    if isinstance(timestamp, int):
        return timestamp if len(str(timestamp)) == 10 else timestamp // 1000
    return timestamp_to_unix(timestamp)
