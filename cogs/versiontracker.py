import disnake
from disnake.ext import commands


class VersionTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
    