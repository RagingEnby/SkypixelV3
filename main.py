import disnake
from disnake.ext import commands

import constants


bot = commands.InteractionBot(
    owner_id=constants.OWNER_ID,
)
constants.BOT = bot


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


bot.run(constants.BOT_TOKEN)
