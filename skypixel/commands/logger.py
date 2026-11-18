import logging
import traceback
from typing import TYPE_CHECKING, Any

import disnake
from disnake.ext import commands

from skypixel import checks, constants, delivery, embed_utils
from skypixel.log_setup import redact
from skypixel.storage.json_store import JsonWrapper

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger = logging.getLogger(__name__)
DM_NOTICE = (
    "Messages you send to Skypixel are forwarded to its owner, @ragingenby. "
    "Use slash commands to use the bot."
)


def prettify_params(options: disnake.AppCmdInter | dict[str, Any]) -> list[str]:
    values: dict[str, Any] = (
        options if isinstance(options, dict) else getattr(options, "options", {})
    )
    params: list[str] = []
    for name, value in values.items():
        if isinstance(value, dict):
            params.append(name)
            params.extend(prettify_params(value))
        else:
            params.append(f"{name}:{value}")
    return params


def prettify_command(inter: disnake.AppCmdInter) -> str:
    return f"/{inter.data.name} {' '.join(prettify_params(inter))}"


def make_command_log_embed(inter: disnake.AppCmdInter) -> disnake.Embed:
    embed = disnake.Embed(
        title=prettify_command(inter),
        color=constants.DEFAULT_EMBED_COLOR,
        timestamp=inter.created_at,
    )
    embed.set_author(
        name=f"{inter.author.name} ({inter.author.id})",
        icon_url=inter.author.display_avatar,
        url=f"https://discord.com/users/{inter.author.id}",
    )
    if inter.guild:
        embed.set_footer(
            text=f"{inter.guild.name} ({inter.guild.id})",
            icon_url=inter.guild.icon.url if inter.guild.icon else None,
        )
    return embed_utils.fit_embed(embed)


def check_error_embed(error: commands.CheckFailure) -> disnake.Embed:
    if isinstance(error, checks.DevServerUnavailable):
        return embed_utils.make_error(
            "Unable to Verify Patreon Membership",
            "I could not verify your Patreon membership. Please contact @ragingenby for support.",
        )
    if isinstance(error, checks.UserNotInDevServer):
        return embed_utils.make_error(
            "Not In Dev Server",
            f"Join [RagingEnby's Dev Server]({constants.DISCORD_INVITE}) to use user commands.",
        )
    if isinstance(error, checks.UserNotAPatron):
        return embed_utils.make_error(
            "Patron Only",
            f"User-installed commands require a [Patreon membership]({constants.PATREON_URL}). Membership costs $5/month.",
        )
    return embed_utils.make_error(
        "Not Allowed", "You are not allowed to use this command."
    )


class LoggerCog(commands.Cog):
    def __init__(self, bot: SkypixelBot):
        self.bot = bot
        self.dm_notices = JsonWrapper(bot.settings.storage_dir / "dmnotices.json")

    @commands.Cog.listener()
    async def on_slash_command(self, inter: disnake.AppCmdInter):
        logger.info("%s used %s", inter.author.name, prettify_command(inter))
        await delivery.send_to_channel(
            self.bot, constants.COMMAND_LOG_CHANNEL, embed=make_command_log_embed(inter)
        )

    @commands.Cog.listener()
    async def on_slash_command_error(
        self, inter: disnake.AppCmdInter, error: commands.CommandError
    ):
        original = getattr(error, "original", error)
        if isinstance(original, commands.CheckFailure):
            await delivery.respond(inter, embed=check_error_embed(original))
            return
        trace = "".join(traceback.format_exception(original))
        logger.error("Command %s failed.", inter.data.name, exc_info=original)
        secrets = (self.bot.settings.bot_token, self.bot.settings.mongodb_uri)
        await delivery.send_to_channel(
            self.bot,
            constants.ERROR_LOG_CHANNEL,
            f"<@{constants.OWNER_ID}>",
            embeds=[
                make_command_log_embed(inter),
                embed_utils.make_error(
                    "Unknown Error",
                    redact(str(original), secrets),
                    f"\n```py\n{redact(trace, secrets)[-3500:]}```",
                ),
            ],
        )
        await delivery.respond(
            inter,
            embed=embed_utils.make_error(
                "Unknown Error",
                "An error occurred while processing your command. Please contact @ragingenby for support.",
            ),
        )

    @commands.Cog.listener()
    async def on_message_command_error(
        self, inter: disnake.MessageCommandInteraction, error: commands.CommandError
    ):
        await self.on_slash_command_error(inter, error)

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot or message.guild:
            return
        if not message.content and not message.attachments:
            return
        logger.info("DM received from %s.", message.author.name)
        embed = disnake.Embed(
            description=message.content or None,
            timestamp=message.created_at,
            color=message.author.color or constants.DEFAULT_EMBED_COLOR,
        )
        embed.set_author(
            name=f"{message.author.display_name} ({message.author.id})",
            icon_url=message.author.display_avatar,
        )
        # Link attachments instead of uploading copies. The links stay on
        # Discord's servers, so the log never holds files the user deleted.
        if message.attachments:
            embed.add_field(
                name="Attachments",
                value="\n".join(attachment.url for attachment in message.attachments),
                inline=False,
            )
        await delivery.send_to_channel(self.bot, constants.DM_LOG_CHANNEL, embed=embed)
        await self.send_dm_notice(message)

    async def send_dm_notice(self, message: disnake.Message) -> None:
        """Tell each user once that the bot's owner can read their DMs."""
        key = str(message.author.id)
        if key in self.dm_notices:
            return
        try:
            await message.channel.send(DM_NOTICE)
        except disnake.HTTPException:
            logger.warning("Cannot send the DM notice to %s.", message.author.name)
            return
        await self.dm_notices.set_and_save(key, True)
