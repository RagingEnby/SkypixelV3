from datetime import datetime
from typing import Literal

import disnake
from disnake.ext import commands

import constants
from modules import utils

# enum would be better but uv was fucking tweaking
# and wouldn't let me install it so Literal works
JoinLeave = Literal['join', 'leave']


class GuildCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @staticmethod
    async def on_bot_joinleave(guild: disnake.Guild, action: JoinLeave):
        if not guild.members:
            # bugged server, skypixel is in 1-2
            return
        verb = "joined" if action == 'join' else "left"
        embed = disnake.Embed(
            title=f"Skypixel {verb} {guild.name}",
            color=constants.COLOR_CODES['a'] if action == 'join' else constants.COLOR_CODES['c'],
            timestamp=datetime.now()
        )
        embed.set_thumbnail(guild.icon.url if guild.icon else None)
        creation_unix = guild.created_at.timestamp()
        embed.add_field(
            name="Guild Info",
            value=f"**ID:** {guild.id}\n**Created:** <t:{creation_unix}> (<t:{creation_unix}:R>)"
        )
        embed.add_field(
            name="Member Info",
            value=f"**Members:** {guild.member_count}\n**Owner:** {guild.owner.mention}"
        )
        await utils.send_to_channel(constants.INVITE_LOG_CHANNEL, embed=embed)

    @staticmethod
    async def on_member_joinleave(member: disnake.Member, action: JoinLeave):
        verb = "joined" if action == 'join' else "left"
        print(f"{member.name} {verb} {member.guild.name}")
        embed = disnake.Embed(
            color=constants.COLOR_CODES['a'] if action == 'join' else constants.COLOR_CODES['c'],
            timestamp=member.joined_at if action == 'left' else datetime.now()
        )
        embed.set_author(
            name=f"{member.display_name} {verb} the server!",
            icon_url=member.display_avatar
        )
        embed.set_footer(
            text=member.guild.name,
            icon_url=member.guild.icon.url if member.guild.icon else None
        )
        await utils.send_to_channel(constants.JOIN_LOG_CHANNEL, member.mention, embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: disnake.Member):
        return await self.on_member_joinleave(member, 'join')

    @commands.Cog.listener()
    async def on_member_remove(self, member: disnake.Member):
        return await self.on_member_joinleave(member, 'leave')

    @commands.Cog.listener()
    async def on_guild_join(self, guild: disnake.Guild):
        return await self.on_bot_joinleave(guild, 'join')

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: disnake.Guild):
        return await self.on_bot_joinleave(guild, 'leave')
