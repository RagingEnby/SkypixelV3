"""Send tracker alerts through the notification outbox."""

import asyncio
from typing import TYPE_CHECKING

import disnake

from skypixel.embed_utils import fit_embed
from skypixel.storage.notifications import notification_fingerprint

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


async def broadcast(
    bot: SkypixelBot,
    channels: dict[int, str],
    *,
    embed: disnake.Embed | None = None,
    embeds: list[disnake.Embed] | None = None,
    ping: bool = True,
) -> None:
    batches = []
    if embeds is None:
        batches.append(None)
    else:
        batch, length = [], 0
        for candidate in embeds:
            fit_embed(candidate)
            if batch and (len(batch) == 10 or length + len(candidate) > 6000):
                batches.append(batch)
                batch, length = [], 0
            batch.append(candidate)
            length += len(candidate)
        if batch:
            batches.append(batch)
    version = notification_fingerprint(
        {
            "channels": channels,
            "ping": ping,
            "embeds": [
                message.to_dict()
                for message in (
                    embeds
                    if embeds is not None
                    else [embed]
                    if embed is not None
                    else []
                )
            ],
        }
    )
    async with bot.notifications.event("broadcast", version):
        for batch in batches:
            kwargs = {"embeds": batch} if batch is not None else {"embed": embed}
            results = await asyncio.gather(
                *(
                    notify_to_channel(
                        bot, channel_id, content if ping else "", **kwargs
                    )
                    for channel_id, content in channels.items()
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result


async def notify_to_channel(
    bot: SkypixelBot,
    channel_id: int,
    content: str | None = None,
    **kwargs,
) -> disnake.Message | None:
    return await bot.notifications.submit(channel_id, content, **kwargs)
