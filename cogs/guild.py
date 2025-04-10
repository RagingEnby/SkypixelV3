from typing import Literal

import disnake
from disnake.ext import commands

# enum would be better but uv was fucking tweaking
# and wouldn't let me install it so Literal works
JoinLeave = Literal['join', 'leave']


class GuildCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @staticmethod
    async def on_member_joinleave(member: disnake.Member, action: JoinLeave):
        print(f"{member.name} {'joined' if action == 'join' else 'left'} {member.guild.name}")

    @commands.Cog.listener()
    async def on_member_join(self, member: disnake.Member):
        return await self.on_member_joinleave(member, 'join')

    @commands.Cog.listener()
    async def on_member_remove(self, member: disnake.Member):
        return await self.on_member_joinleave(member, 'leave')
