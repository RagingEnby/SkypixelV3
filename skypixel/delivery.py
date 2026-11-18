"""Send messages to a command user or a Discord channel."""

import logging
from contextlib import suppress

import disnake

from skypixel.embed_utils import fit_embed, fit_embeds, make_error

logger = logging.getLogger(__name__)


async def respond(
    inter: disnake.Interaction, *, embed: disnake.Embed, ephemeral: bool = True
) -> None:
    embed = fit_embed(embed)
    if not inter.response.is_done():
        await inter.response.send_message(embed=embed, ephemeral=ephemeral)
        return
    if ephemeral:
        # The first followup replaces the public "thinking" message and is
        # public too. Delete that placeholder so this message can be private.
        with suppress(disnake.HTTPException):
            original = await inter.original_response()
            if original.flags.loading:
                await original.delete()
    await inter.followup.send(embed=embed, ephemeral=ephemeral)


async def send_error(inter: disnake.Interaction, title: str, *args) -> None:
    """Show an error to the user who ran the command, and to nobody else."""
    await respond(inter, embed=make_error(title, *args))


async def send_to_channel(
    bot: disnake.Client,
    channel_id: int,
    *args,
    thread_id: int | None = None,
    **kwargs,
) -> disnake.Message | None:
    channel = bot.get_channel(channel_id)
    if thread_id is not None:
        if not isinstance(channel, (disnake.TextChannel, disnake.ForumChannel)):
            logger.warning("Cannot find the parent channel %s.", channel_id)
            return None
        target = channel.get_thread(thread_id)
    else:
        target = channel if isinstance(channel, disnake.TextChannel) else None
    if target is None:
        logger.warning("Cannot find channel %s or thread %s.", channel_id, thread_id)
        return None
    if embed := kwargs.get("embed"):
        fit_embed(embed)
    if "embeds" in kwargs:
        kwargs["embeds"] = fit_embeds(kwargs["embeds"])
    try:
        return await target.send(*args, **kwargs)
    except disnake.HTTPException:
        logger.exception(
            "Cannot send to channel %s or thread %s.", channel_id, thread_id
        )
        return None
