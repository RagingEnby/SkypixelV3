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

logger = logging.getLogger('disnake')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='storage/disnake.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

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


async def on_close(sig: int):
    print(f"Logging out ({signal.Signals(sig).name})...")
    asyncreqs.CLOSED = True
    if asyncreqs.SESSION and not asyncreqs.SESSION.closed:
        await asyncreqs.SESSION.close()
    print("Closed aiohttp session")
    await asyncio.gather(*[
        cog.close() for cog in bot.cogs.values()  # type: ignore
        if hasattr(cog, 'close') and callable(cog.close)
    ])
    print("Closed all cogs")
    await bot.close()
    print("Closed bot")
    sys.exit(0)


@bot.event
async def on_ready():
    def signal_handler(sig: int, _):
        asyncio.create_task(on_close(sig))
    signal.signal(signal.SIGINT, signal_handler)
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


bot.run(constants.BOT_TOKEN)
