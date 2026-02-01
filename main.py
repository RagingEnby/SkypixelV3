import asyncio
import logging
import signal
import sys
import traceback

import disnake
from disnake.ext import commands

import constants
from cogs import AlphaTrackerCog
from cogs import AuctionTrackerCog
from cogs import FireSaleTrackerCog
from cogs import GuildCog
from cogs import ItemDBCog
from cogs import LoggerCog
from cogs import MotdTrackerCog
from cogs import RankTrackerCog
from cogs import StatusUpdaterCog
from cogs import VersionTrackerCog
from cogs import WikiTrackerCog
from cogs import ZoneTrackerCog
from cogs import JobTrackerCog
from modules import asyncreqs
from modules import utils

# load Skypixel logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_handler = logging.FileHandler(
    filename="storage/skypixel.log", encoding="utf-8", mode="w"
)
root_handler.setFormatter(
    logging.Formatter("[%(asctime)s:%(levelname)s:%(name)s:%(lineno)d] %(message)s")
)

root_logger.addHandler(root_handler)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("[%(levelname)s:%(name)s:%(lineno)d] %(message)s")
)
root_logger.addHandler(console_handler)
logger = logging.getLogger(__name__)

# load disnake logger
disnake_logger = logging.getLogger("disnake")
disnake_logger.setLevel(logging.DEBUG)
disnake_handler = logging.FileHandler(
    filename="storage/disnake.log", encoding="utf-8", mode="w"
)
disnake_handler.setFormatter(
    logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
)
disnake_logger.addHandler(disnake_handler)
disnake_logger.propagate = False


intents = disnake.Intents.default()
intents.members = True  # type: ignore
bot = commands.InteractionBot(
    intents=intents,
    owner_id=constants.OWNER_ID,
)
bot.add_cog(AlphaTrackerCog(bot))
bot.add_cog(AuctionTrackerCog(bot))
bot.add_cog(FireSaleTrackerCog(bot))
bot.add_cog(GuildCog(bot))
bot.add_cog(ItemDBCog(bot))
bot.add_cog(LoggerCog(bot))
bot.add_cog(MotdTrackerCog(bot))
bot.add_cog(RankTrackerCog(bot))
bot.add_cog(StatusUpdaterCog(bot))
bot.add_cog(VersionTrackerCog(bot))
bot.add_cog(WikiTrackerCog(bot))
bot.add_cog(ZoneTrackerCog(bot))
bot.add_cog(JobTrackerCog(bot))
constants.BOT = bot
logger.debug("Loaded all cogs + set constants.BOT")


# put here instead of a cog so it has main.py's scope
@bot.message_command(name="Execute")
async def execute(inter: disnake.MessageCommandInteraction, message: disnake.Message):
    if not await bot.is_owner(inter.author):
        return await inter.send(
            embed=utils.make_error(
                "Not Owner", "You must be the bot owner to use this command!"
            )
        )
    await inter.response.defer()
    try:
        tmp_dic = {}
        clean_content = message.content.replace("\u2069", "").replace("\u2068", "")
        
        executing_string = "async def temp_func():\n    {}\n".format(
            clean_content.partition("\n")[2]
            .strip("`")
            .replace("\n", "    \n    ")
            .replace("”", '"')
            .replace("’", "'")
            .replace("‘", "'")
        )
        logger.info(executing_string)
        exec(executing_string, {**globals(), **locals()}, tmp_dic)
        await tmp_dic["temp_func"]()
        await message.add_reaction("✅")
    except:  # noqa: E722
        error = traceback.format_exc()
        logger.error(error)
        await asyncio.gather(
            message.add_reaction("❌"),
            inter.send(f"Error while running code:\n```py\n{error}```"),
        )


async def on_close():
    logger.info("Shutting down...")

    await asyncreqs.close()
    logger.info("Closed asyncreqs")

    # PYRIGHT I PROMISE THIS CODE WORKS PLEASE SHUT UP
    await asyncio.gather(  # pyright: ignore[reportCallIssue]
        *[  # pyright: ignore[reportArgumentType]
            cog.close()  # pyright: ignore[reportAttributeAccessIssue]
            for cog in bot.cogs.values()
            if hasattr(cog, "close") and callable(cog.close)   # pyright: ignore[reportAttributeAccessIssue]
        ]
    )
    logger.info("Closed all cogs")

    await bot.close()
    logger.info("Closed bot")

    sys.exit(0)


@bot.event
async def on_ready():
    def signal_handler(*_):
        asyncio.create_task(on_close())

    signal.signal(signal.SIGINT, signal_handler)
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")


bot.run(constants.BOT_TOKEN)
