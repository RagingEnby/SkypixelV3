import disnake
from disnake.ext import commands
import signal
import asyncio

from modules import asyncreqs

import constants


bot = commands.InteractionBot(
    owner_id=constants.OWNER_ID,
)
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
