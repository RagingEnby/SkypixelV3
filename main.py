import asyncio
import logging
import signal
import sys

import disnake
from disnake.ext import commands

import constants
from cogs import AlphaTrackerCog
from cogs import AuctionTrackerCog
from cogs import FireSaleTrackerCog
from cogs import GuildCog
from cogs import ItemSearchCog
from cogs import LoggerCog
from cogs import MotdTrackerCog
from cogs import RankTrackerCog
from cogs import VersionTrackerCog
from cogs import WikiTrackerCog
from cogs import ZoneTrackerCog
from modules import asyncreqs

# load Skypixel logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_handler = logging.FileHandler(filename='storage/skypixel.log', encoding='utf-8', mode='w')
root_handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
root_logger.addHandler(root_handler)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('[%(levelname)s:%(name)s]  %(message)s'))
root_logger.addHandler(console_handler)
logger = logging.getLogger(__name__)

# load disnake logger
disnake_logger = logging.getLogger('disnake')
disnake_logger.setLevel(logging.DEBUG)
disnake_handler = logging.FileHandler(filename='storage/disnake.log', encoding='utf-8', mode='w')
disnake_handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
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
bot.add_cog(ItemSearchCog(bot))
bot.add_cog(LoggerCog(bot))
bot.add_cog(MotdTrackerCog(bot))
bot.add_cog(RankTrackerCog(bot))
bot.add_cog(VersionTrackerCog(bot))
bot.add_cog(WikiTrackerCog(bot))
bot.add_cog(ZoneTrackerCog(bot))
constants.BOT = bot
logger.debug("Loaded all cogs + set constants.BOT")


async def on_close():
    logger.info(f"Logging out...")

    asyncreqs.CLOSED = True
    # use a try except loop instead of `if asyncreqs.SESSION and not
    # asyncreqs.SESSION.closed` because sometimes .closed on aiohttp.ClientSession bugs out
    try:
        await asyncreqs.SESSION.close()
        logger.info("Closed aiohttp session")
    except Exception as e:
        logger.warning(f"unable to close asyncreqs session {e} (this is 99% prob ok)")

    await asyncio.gather(*[
        cog.close() for cog in bot.cogs.values()  # type: ignore
        if hasattr(cog, 'close') and callable(cog.close)
    ])
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
