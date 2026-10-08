import asyncio
import logging
from pathlib import Path
from uuid import uuid4

import disnake

from skypixel.storage.json import JsonWrapper

logger = logging.getLogger(__name__)


class NotificationOutbox:
    """Save tracker alerts until Discord accepts each message."""

    def __init__(self, bot: disnake.Client, path: Path):
        self.bot = bot
        self.pending = JsonWrapper(path)
        self._delivery_lock = asyncio.Lock()

    async def submit(
        self,
        channel_id: int,
        content: str | None = None,
        *,
        thread_id: int | None = None,
        embed: disnake.Embed | None = None,
        embeds: list[disnake.Embed] | None = None,
    ) -> disnake.Message | None:
        from skypixel import utils

        messages = (
            embeds if embeds is not None else [embed] if embed is not None else []
        )
        key = uuid4().hex
        await self.pending.set_and_save(
            key,
            {
                "channel_id": channel_id,
                "thread_id": thread_id,
                "content": content,
                "embeds": [message.to_dict() for message in utils.fit_embeds(messages)],
            },
        )
        async with self._delivery_lock:
            return await self._deliver(key)

    async def _deliver(self, key: str) -> disnake.Message | None:
        from skypixel import utils

        message = self.pending.get(key)
        if message is None:
            return None
        result = await utils.send_to_channel(
            self.bot,
            message["channel_id"],
            message["content"],
            thread_id=message["thread_id"],
            embeds=[disnake.Embed.from_dict(embed) for embed in message["embeds"]],
        )
        if result is not None:
            await self.pending.remove_and_save(key)
        return result

    async def flush(self) -> None:
        async with self._delivery_lock:
            for key in list(self.pending):
                await self._deliver(key)

    async def run(self) -> None:
        while True:
            try:
                await self.flush()
            except Exception:
                logger.exception("Cannot deliver pending tracker alerts.")
            await asyncio.sleep(15)
