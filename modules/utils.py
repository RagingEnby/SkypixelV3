import disnake
import re

def make_error(title: str, *args) -> disnake.Embed:
    return disnake.Embed(
        title=title,
        description='\n'.join([str(arg) for arg in args]),
        color=disnake.Color.red()
    )


def remove_color_codes(string: str) -> str:
    return re.sub(r"§[0-9a-fA-Fklmnor]", "", string)
