import datetime
import json
import random
import re
from contextlib import suppress
from urllib.parse import quote

import aiofiles
import disnake

import constants
from modules import hypixel


async def write_json(file_path: str, data: dict, indent: int = 2):
    async with aiofiles.open(file_path, 'w') as file:
        await file.write(json.dumps(data, indent=indent))


def make_error(title: str, *args) -> disnake.Embed:
    return add_footer(disnake.Embed(
        title=title,
        description='\n'.join([str(arg) for arg in args]),
        color=disnake.Color.red()
    ))


def remove_color_codes(string: str) -> str:
    string = re.sub(r"§[0-9a-fA-Fklmnor]", "", string)
    return re.sub(r"&[0-9a-fA-Fklmnor]", "", string)


def esc_mrkdwn(string: str) -> str:
    return disnake.utils.escape_markdown(string)


def add_footer(embed: disnake.Embed) -> disnake.Embed:
    text = random.choice(list(constants.CREDIT_FOOTERS))
    return embed.set_footer(text=text, icon_url=constants.OWNER_PFP)


async def send_to_channel(channel_id: int, *args, **kwargs) -> disnake.Message | None:
    channel = constants.BOT.get_channel(channel_id)
    if not channel:
        return
    return await channel.send(*args, **kwargs)  # type: ignore


def to_mc_text(text: str) -> str:
    url = constants.MC_TEXT_IMAGE.format(quote(text))
    return url


def get_item_image(item_id: str, color: str | None = None) -> str:
    default = constants.ITEM_IMAGE.format(item_id)
    if not color:
        return default
    try:
        material = hypixel.get_material(item_id)
    except KeyError as e:
        print('unable to find material for item:', e)
        return default
    if not material.startswith('LEATHER_'):
        return default
    armor_type = material.replace('LEATHER_', '').lower()
    return constants.LEATHER_IMAGE.format(armor_type, color)


# shout out some random guy on stack overflow for this one
def numerize(num: int | float) -> str:
    if num < 1_000:
        return str(num)
    suffixes = ["", "K", "M", "B", "T"]
    magnitude = 0
    while abs(num) >= 1_000 and magnitude < len(suffixes) - 1:
        num /= 1_000
        magnitude += 1
    return f"{num:.2f}".rstrip("0").rstrip(".") + suffixes[magnitude]


def commaize(num: int | float) -> str:
    return '{:,}'.format(num)


def timestamp_to_unix(date_str: str) -> int:
    if 'L' in date_str:
        date_str = date_str.replace('L', '')
        return int(date_str.split('L')[0])

    with suppress(ValueError):
        return int(date_str)

    dt = None
    with suppress(ValueError):
        date_format = '%m/%d/%y %I:%M %p'
        dt = datetime.datetime.strptime(date_str, date_format)
    if dt is None:
        with suppress(ValueError):
            date_format = '%d/%m/%y %H:%M'
            dt = datetime.datetime.strptime(date_str, date_format)
    if dt is None:
        raise ValueError('invalid timestamp:', date_str)
    return int(dt.timestamp())


def normalize_timestamp(timestamp: str | int) -> int:
    if isinstance(timestamp, int):
        return timestamp
    return timestamp_to_unix(timestamp)
