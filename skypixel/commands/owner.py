import asyncio
import logging
import textwrap
import traceback

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http

logger = logging.getLogger(__name__)


def register(bot: commands.InteractionBot) -> None:
    # The command runs any code the owner sends. Register it in the dev server
    # only, so no other server or user install lists it.
    @bot.message_command(name="Execute", guild_ids=[constants.DEV_SERVER_ID])
    async def execute(
        inter: disnake.MessageCommandInteraction, message: disnake.Message
    ):
        if not await bot.is_owner(inter.author):
            return await inter.send(
                embed=utils.make_error(
                    "Not Owner", "You must be the bot owner to use this command!"
                )
            )
        await inter.response.defer()
        try:
            clean_content = message.content.replace("\u2069", "").replace("\u2068", "")
            source = clean_content.partition("\n")[2].strip("`")
            source = (
                source.replace("\u201d", '"')
                .replace("\u2019", "'")
                .replace("\u2018", "'")
            )
            code = "async def temp_func():\n" + textwrap.indent(source, "    ") + "\n"
            namespace = {
                **globals(),
                **locals(),
                "constants": constants,
                "http": http,
                **{name: type(cog) for name, cog in bot.cogs.items()},
            }
            exec(compile(code, "<owner command>", "exec"), namespace)
            await namespace["temp_func"]()
            await message.add_reaction("\u2705")
        except Exception:
            error = traceback.format_exc()
            logger.exception("The owner command failed.")
            await asyncio.gather(
                message.add_reaction("\u274c"),
                inter.send(f"Error while running code:\n```py\n{error[-1900:]}```"),
            )
