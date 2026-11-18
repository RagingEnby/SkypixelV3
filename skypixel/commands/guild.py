import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import disnake
from disnake.ext import commands

from skypixel import constants, delivery

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger: logging.Logger = logging.getLogger(__name__)
JoinLeave = Literal["join", "leave"]


class GuildCog(commands.Cog):
    def __init__(self, bot: SkypixelBot) -> None:
        self.bot: SkypixelBot = bot

    async def on_bot_joinleave(self, guild: disnake.Guild, action: JoinLeave) -> None:
        if not guild.members:
            return
        verb = "joined" if action == "join" else "left"
        embed = disnake.Embed(
            title=f"Skypixel {verb} {guild.name}",
            color=constants.COLOR_CODES["a"]
            if action == "join"
            else constants.COLOR_CODES["c"],
            timestamp=datetime.now(UTC),
        )
        embed.set_thumbnail(guild.icon.url if guild.icon else None)
        creation_unix = int(guild.created_at.timestamp())
        embed.add_field(
            name="Guild Info",
            value=f"**ID:** {guild.id}\n**Created:** <t:{creation_unix}> (<t:{creation_unix}:R>)",
        )
        embed.add_field(
            name="Member Info",
            value=f"**Members:** {guild.member_count}\n**Owner:** {guild.owner.mention if guild.owner else '`Unknown`'}",
        )
        await delivery.send_to_channel(
            self.bot, constants.INVITE_LOG_CHANNEL, embed=embed
        )

    async def on_member_joinleave(
        self, member: disnake.Member, action: JoinLeave
    ) -> None:
        if member.guild.id != constants.DEV_SERVER_ID:
            return
        verb = "joined" if action == "join" else "left"
        logger.info("%s %s %s", member.name, verb, member.guild.name)
        embed = disnake.Embed(
            color=constants.COLOR_CODES["a"]
            if action == "join"
            else constants.COLOR_CODES["c"],
            timestamp=member.joined_at if action == "leave" else datetime.now(UTC),
        )
        embed.set_author(
            name=f"{member.display_name} {verb} the server!",
            icon_url=member.display_avatar,
        )
        embed.set_footer(
            text=member.guild.name,
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )
        await delivery.send_to_channel(
            self.bot, constants.JOIN_LOG_CHANNEL, member.mention, embed=embed
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: disnake.Member) -> None:
        return await self.on_member_joinleave(member, "join")

    @commands.Cog.listener()
    async def on_member_remove(self, member: disnake.Member) -> None:
        return await self.on_member_joinleave(member, "leave")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: disnake.Guild) -> None:
        return await self.on_bot_joinleave(guild, "join")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: disnake.Guild) -> None:
        return await self.on_bot_joinleave(guild, "leave")
