import logging
import traceback
from contextlib import suppress

import disnake
from disnake.ext import commands

import constants
from modules import utils

logger = logging.getLogger(__name__)


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
        logger.info(f"{inter.author.name} used {full_command}")
        embed = make_command_log_embed(inter)
        await utils.send_to_channel(constants.COMMAND_LOG_CHANNEL, embed=embed)

    @commands.Cog.listener()
    async def on_slash_command_error(self, inter: disnake.AppCmdInter, e: commands.CommandError):
        if isinstance(e, commands.CheckFailure):
            err_name = e.__class__.__name__
            if err_name == "DevServerUnavailable":
                embed = utils.make_error(
                    "Unable to Verify Patreon Membership",
                    "Using Skypixel as a user-installed bot is only supported for patrons, I was unable to verify your membership. Please reach out to @ragingenby for support.",
                )
            elif err_name == "UserNotInDevServer":
                embed = utils.make_error(
                    "Not In Dev Server",
                    f"You must be in [RagingEnby's Dev Server]({constants.DISCORD_INVITE}) to use user commands.",
                )
            elif err_name == "UserNotAPatron":
                embed = utils.make_error(
                    "Patron Only",
                    f"In order to use user-installed commands, you must be a Patreon member. This costs $5/month and supports me greatly, you can join [here!]({constants.PATREON_URL})",
                )
            else:
                embed = utils.make_error(
                    "Not Allowed",
                    "You are not allowed to use this command.",
                )
            if inter.response.is_done():
                await inter.followup.send(embed=embed, ephemeral=True)
            else:
                await inter.response.send_message(embed=embed, ephemeral=True)
            return
        err = ''.join(traceback.format_exception(
            type(e), e, e.__traceback__
        ))
        logger.error(f"Exception in slash command {inter.application_command.name!r}:\n{err}")
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

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot or message.guild or not message.content:
            return
        logger.info(f"dm received: <{message.author.name}> {message.content}")
        embed = disnake.Embed(
            description=message.content,
            timestamp=message.created_at,
            color=message.author.color or constants.DEFAULT_EMBED_COLOR
        )
        embed.set_author(
            name=f"{message.author.display_name} ({message.author.id})",
            icon_url=message.author.display_avatar
        )
        await utils.send_to_channel(constants.DM_LOG_CHANNEL, embed=embed, attachments=message.attachments)
