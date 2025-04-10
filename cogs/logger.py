import disnake
from disnake.ext import commands
from contextlib import suppress
import traceback

from modules import utils

import constants


def get_log_params(inter: disnake.AppCmdInter) -> list[str]:
    log_params = []

    # we want to first find out if this is a subcommand and if so, set the name as the first param
    for param, value in inter.options.items():
        if isinstance(value, dict): # the only time this will be true is if this is a subcommand or disnake breaks shit
            log_params.append(param + ' ') # add in some padding for fanciness

    for param, value in inter.filled_options.items():
        log_params.append(f"{param}:{value}")
    return log_params



def prettify_params(inter: disnake.AppCmdInter) -> str:
    log_params = get_log_params(inter)
    return (' ' if len(log_params) > 0 else '') + ' '.join(log_params)


def prettify_command(inter: disnake.AppCmdInter, pretty_params: str | None = None) -> str:
    if not pretty_params:
        pretty_params = prettify_params(inter)
    return f"/{inter.data.name}{pretty_params}"


def make_command_log_embed(inter: disnake.AppCmdInter) -> disnake.Embed:
    full_command = prettify_command(inter)
    embed = disnake.Embed(
        title=full_command,
        color=constants.DEFAULT_EMBED_COLOR,
        timestamp=inter.created_at
    )
    embed.set_author(
        name=f"{inter.author.name} ({inter.author.id})",
        icon_url=inter.author.display_avatar,
        url=f"https://discord.com/users/{inter.author.id}"
    )
    if inter.guild:
        embed.set_footer(
            text=f"{inter.guild.name} ({inter.guild.id})",
            icon_url=inter.guild.icon.url if inter.guild.icon else None
        )
    return embed


class LoggerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_slash_command(self, inter: disnake.AppCmdInter):
        full_command = prettify_command(inter)
        print(f"{inter.author.name} used {full_command}")

    @commands.Cog.listener()
    async def on_slash_command_error(self, inter: disnake.AppCmdInter, e: commands.CommandError):
        err = traceback.format_exc()
        print('command error:', err)
        with suppress(Exception):
            await inter.response.defer()
        await inter.send(embed=utils.make_error(
            "Unknown Error",
            "An unknown error occured while processing your command, this has been forwarded to the bot owner."
        ))
        await utils.send_to_channel(
            constants.ERROR_LOG_CHANNEL,
            embeds=[
                make_command_log_embed(inter),
                utils.make_error(
                    "Unknown Error",
                    str(e), f"\n```\n{err}```"
                )
            ]
        )
        