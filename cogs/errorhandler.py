from disnake.ext import commands


class ErrorHandlerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        