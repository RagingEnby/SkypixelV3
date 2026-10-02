import asyncio
import logging
import textwrap
import traceback

import disnake
from disnake.ext import commands

from skypixel import constants, extensions
from skypixel import discord as utils
from skypixel.clients import http as asyncreqs

logger = logging.getLogger(__name__)


def register(bot: commands.InteractionBot) -> None:
    @bot.message_command(
        name="Execute",
        install_types=disnake.ApplicationInstallTypes.all(),
        contexts=disnake.InteractionContextTypes.all(),
    )
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
                **{
                    name: extensions.get_extension(name)
                    for name in extensions.EXTENSIONS
                },
            }
            exec(compile(code, "<owner command>", "exec"), namespace)  # noqa: S102
            await namespace["temp_func"]()
            await message.add_reaction("\u2705")
        except Exception:  # noqa: BLE001
            error = traceback.format_exc()
            logger.exception("The owner command failed.")
            await asyncio.gather(
                message.add_reaction("\u274c"),
                inter.send(f"Error while running code:\n```py\n{error[-1900:]}```"),
            )
