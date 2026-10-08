import logging
import traceback

import disnake
from disnake.ext import commands

from skypixel import checks, constants, utils
from skypixel.logging import redact
from skypixel.settings import settings

logger = logging.getLogger(__name__)
# Discord's default upload limit for bots is 10 MiB per message.
ATTACHMENT_BUDGET = 8 * 1024 * 1024


def prettify_params(options: disnake.AppCmdInter | dict) -> list[str]:
    if not isinstance(options, dict):
        options = getattr(options, "options", {})
    params = []
    for name, value in options.items():
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
    return utils.fit_embed(embed)


def check_error_embed(error: commands.CheckFailure) -> disnake.Embed:
    if isinstance(error, checks.DevServerUnavailable):
        return utils.make_error(
            "Unable to Verify Patreon Membership",
            "I could not verify your Patreon membership. Please contact @ragingenby for support.",
        )
    if isinstance(error, checks.UserNotInDevServer):
        return utils.make_error(
            "Not In Dev Server",
            f"Join [RagingEnby's Dev Server]({constants.DISCORD_INVITE}) to use user commands.",
        )
    if isinstance(error, checks.UserNotAPatron):
        return utils.make_error(
            "Patron Only",
            f"User-installed commands require a [Patreon membership]({constants.PATREON_URL}). Membership costs $5/month.",
        )
    return utils.make_error("Not Allowed", "You are not allowed to use this command.")


class LoggerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_slash_command(self, inter: disnake.AppCmdInter):
        logger.info("%s used %s", inter.author.name, prettify_command(inter))
        await utils.send_to_channel(
            constants.COMMAND_LOG_CHANNEL, embed=make_command_log_embed(inter)
        )

    @commands.Cog.listener()
    async def on_slash_command_error(
        self, inter: disnake.AppCmdInter, error: commands.CommandError
    ):
        original = getattr(error, "original", error)
        if isinstance(original, commands.CheckFailure):
            await utils.respond(inter, embed=check_error_embed(original))
            return
        trace = "".join(traceback.format_exception(original))
        logger.error("Command %s failed.", inter.data.name, exc_info=original)
        secrets = (settings.bot_token, settings.mongodb_uri)
        await utils.send_to_channel(
            constants.ERROR_LOG_CHANNEL,
            f"<@{constants.OWNER_ID}>",
            embeds=[
                make_command_log_embed(inter),
                utils.make_error(
                    "Unknown Error",
                    redact(str(original), secrets),
                    f"\n```py\n{redact(trace, secrets)[-3500:]}```",
                ),
            ],
        )
        await utils.respond(
            inter,
            embed=utils.make_error(
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
        files, links, size = [], [], 0
        for attachment in message.attachments:
            # Large files would make the whole log message fail, so link them.
            if size + attachment.size <= ATTACHMENT_BUDGET:
                files.append(await attachment.to_file())
                size += attachment.size
            else:
                links.append(attachment.url)
        if links:
            embed.add_field(name="Attachments", value="\n".join(links), inline=False)
        await utils.send_to_channel(constants.DM_LOG_CHANNEL, embed=embed, files=files)
