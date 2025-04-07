import disnake
import re
import aiofiles
import json
import random

import constants


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
    return re.sub(r"§[0-9a-fA-Fklmnor]", "", string)


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
    