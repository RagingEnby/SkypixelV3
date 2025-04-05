import disnake
import re
import aiofiles
import json


async def write_json(file_path: str, data: dict, indent: int = 2):
    async with aiofiles.open(file_path, 'w') as file:
        await file.write(json.dumps(data, indent=indent))


def make_error(title: str, *args) -> disnake.Embed:
    return disnake.Embed(
        title=title,
        description='\n'.join([str(arg) for arg in args]),
        color=disnake.Color.red()
    )


def remove_color_codes(string: str) -> str:
    return re.sub(r"§[0-9a-fA-Fklmnor]", "", string)


def esc_mrkdwn(string: str) -> str:
    return disnake.utils.escape_markdown(string)
    