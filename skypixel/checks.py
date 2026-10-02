from contextlib import suppress

import disnake
from disnake.ext import commands

from skypixel import constants


class DevServerUnavailable(commands.CheckFailure):
    pass


class UserNotInDevServer(commands.CheckFailure):
    pass


class UserNotAPatron(commands.CheckFailure):
    pass


async def patron_only_check(
    bot: commands.InteractionBot, inter: disnake.Interaction
) -> bool:
    owners = inter.authorizing_integration_owners
    if owners is None or owners.user_id is None:
        return True
    guild = bot.get_guild(constants.DEV_SERVER_ID)
    if guild is None:
        raise DevServerUnavailable("The dev server is unavailable.")
    member = guild.get_member(inter.author.id)
    if member is None:
        try:
            with suppress(disnake.NotFound):
                member = await guild.fetch_member(inter.author.id)
        except disnake.HTTPException as error:
            raise DevServerUnavailable(
                "Cannot check the patron role in the dev server."
            ) from error
    if member is None:
        raise UserNotInDevServer("Join the dev server to use this command.")
    if not member.get_role(constants.PATRON_ROLE):
        raise UserNotAPatron("This command requires the patron role.")
    return True
