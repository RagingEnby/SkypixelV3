import disnake
from disnake.ext import commands
import signal
import asyncio
import logging

from modules import asyncreqs
from cogs import ItemSearchCog
from cogs import VersionTrackerCog

import constants


logger = logging.getLogger('disnake')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='disnake.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


bot = commands.InteractionBot(
    owner_id=constants.OWNER_ID,
)
bot.add_cog(ItemSearchCog(bot))
bot.add_cog(VersionTrackerCog(bot))
constants.BOT = bot


async def on_close(sig: int):
    print(f"Logging out ({signal.Signals(sig).name})...")
    if asyncreqs.SESSION and not asyncreqs.SESSION.closed:
        await asyncreqs.SESSION.close()
    await bot.close()


@bot.event
async def on_ready():
    def signal_handler(sig: int, _):
        asyncio.create_task(on_close(sig))
    signal.signal(signal.SIGINT, signal_handler)
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


bot.run(constants.BOT_TOKEN)
