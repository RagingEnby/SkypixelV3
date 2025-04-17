import asyncio
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

    @commands.message_command(
        name="Execute"
    )
    async def execute(self, inter: disnake.MessageCommandInteraction, message: disnake.Message):
        if not await self.bot.is_owner(inter.author):
            return await inter.send(embed=utils.make_error(
                "Not Owner",
                "You must be the bot owner to use this command!"
            ))
        await inter.response.defer()
        try:
            tmp_dic = {}
            executing_string = "async def temp_func():\n    {}\n".format(
                message.content.partition("\n")[2].strip("`") \
                    .replace("\n", "    \n    ") \
                    .replace('”', '"') \
                    .replace("’", "'") \
                    .replace("‘", "'"))
            logger.info(executing_string)
            exec(executing_string, {**globals(), **locals()}, tmp_dic)
            await tmp_dic['temp_func']()
            await message.add_reaction('✅')
        except:  # type: ignore
            error = traceback.format_exc()
            logger.error(error)
            await asyncio.gather(
                message.add_reaction('❌'),
                message.reply(f"Error while running code:\n```py\n{error}```")
            )
