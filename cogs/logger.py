import traceback
from contextlib import suppress

import disnake
from disnake.ext import commands

import constants
from modules import utils


def prettify_params(options: disnake.AppCmdInter | dict) -> list[str]:
    if isinstance(options, disnake.AppCmdInter):
        options = options.options
    log_params = []
    for param, value in options.items():
        if isinstance(value, dict): # if this is a subcommand
            log_params.append(param)
            log_params.extend(prettify_params(value))
        else:
            log_params.append(f"{param}:{value}")
    return log_params


def prettify_command(inter: disnake.AppCmdInter) -> str:
    return f"/{inter.data.name} {' '.join(prettify_params(inter))}"


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
        embed = make_command_log_embed(inter)
        await utils.send_to_channel(constants.COMMAND_LOG_CHANNEL, embed=embed)

    @commands.Cog.listener()
    async def on_slash_command_error(self, inter: disnake.AppCmdInter, e: commands.CommandError):
        err = ''.join(traceback.format_exception(
            type(e), e, e.__traceback__
        ))
        print(f"Exception in slash command {inter.application_command.name!r}:\n{err}")
        with suppress(Exception):
            await inter.response.defer()
        await inter.send(embed=utils.make_error(
            "Unknown Error",
            "An unknown error occured while processing your command, this has been forwarded to the bot owner."
        ))
        await utils.send_to_channel(
            constants.ERROR_LOG_CHANNEL,
            f"<@{constants.OWNER_ID}>",
            embeds=[
                make_command_log_embed(inter),
                utils.make_error(
                    "Unknown Error",
                    str(e), f"\n```py\n{err}```"
                )
            ]
        )
