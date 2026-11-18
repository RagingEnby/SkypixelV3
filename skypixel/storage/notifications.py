import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import disnake

from skypixel import constants, delivery, embed_utils
from skypixel.storage.json_store import JsonWrapper

logger = logging.getLogger(__name__)


def notification_fingerprint(data: dict) -> str:
    data = deepcopy(data)
    for embed in data.get("embeds", []):
        if embed.get("footer", {}).get("text") in constants.CREDIT_FOOTERS:
            embed.pop("footer")
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class NotificationStorageError(OSError):
    pass


class NotificationOutbox:
    """Save tracker alerts and delivery records until the tracker commits its state.

    A tracker poll can send several alerts and then fail before it saves its
    own state. The next poll sees the same change and sends the same alerts.
    The outbox stops those repeats with two files.

    notifications.json holds pending messages. submit() saves a message there
    before it sends it and removes it after Discord accepts it. run() retries
    whatever is left every 15 seconds.

    notifications.events.json holds one event for each poll that sent an alert.
    The event's version is a fingerprint of the tracker's state before the
    poll, so a retried poll gets the same version and joins the same event.
    The event lists the messages already delivered, and submit() skips those.

    An event is complete when its poll returns without an error. It is deleted
    once no pending message refers to it. If the same tracker starts an event
    with a different version, the tracker saved its state before the old event
    was marked, so _begin_event() completes the old event.

    A message sent outside a poll gets an event of its own.

    A message that cannot be sent is retried after 15 seconds, then after
    twice as long each time, up to 15 minutes. After max_age seconds it is
    dropped, so a deleted channel cannot hold a message forever.
    """

    max_age = 6 * 60 * 60
    retry_delay = 15
    max_retry_delay = 15 * 60

    def __init__(self, bot: disnake.Client, path: Path):
        self.bot = bot
        self.pending = JsonWrapper(path)
        self.events = JsonWrapper(path.with_suffix(".events.json"))
        self._delivery_lock = asyncio.Lock()
        # Failed sends for each pending key, and when run() may try it again.
        self._failures: dict[str, int] = {}
        self._retry_at: dict[str, float] = {}
        self._event: ContextVar[dict | None] = ContextVar(
            "notification_event", default=None
        )

    @asynccontextmanager
    async def event(self, source: str, version: str):
        if self._event.get() is not None:
            yield
            return
        context = {"source": source, "version": version, "id": None}
        token = self._event.set(context)
        try:
            yield
            if context["id"] is not None:
                async with self._delivery_lock:
                    key = context["id"]
                    await self.events.set_and_save(
                        key, {**self.events[key], "complete": True}
                    )
                    await self._clean_event(key)
        finally:
            self._event.reset(token)

    async def _begin_event(self, context: dict) -> str:
        if context["id"] is not None:
            return context["id"]
        for key, event in list(self.events.items()):
            if event["source"] != context["source"] or event["complete"]:
                continue
            if event["version"] == context["version"]:
                context["id"] = key
                return key
            # The tracker committed its state before cleanup could finish.
            await self.events.set_and_save(key, {**event, "complete": True})
            await self._clean_event(key)
        key = uuid4().hex
        await self.events.set_and_save(
            key,
            {
                "source": context["source"],
                "version": context["version"],
                "complete": False,
                "delivered": [],
            },
        )
        context["id"] = key
        return key

    async def submit(
        self,
        channel_id: int,
        content: str | None = None,
        *,
        thread_id: int | None = None,
        embed: disnake.Embed | None = None,
        embeds: list[disnake.Embed] | None = None,
    ) -> disnake.Message | None:
        messages = (
            embeds if embeds is not None else [embed] if embed is not None else []
        )
        message = {
            "channel_id": channel_id,
            "thread_id": thread_id,
            "content": content,
            "embeds": [
                message.to_dict() for message in embed_utils.fit_embeds(messages)
            ],
        }
        context = self._event.get()
        if context is None:
            async with self.event(
                f"direct:{channel_id}:{thread_id}", notification_fingerprint(message)
            ):
                return await self.submit(
                    channel_id, content, thread_id=thread_id, embed=embed, embeds=embeds
                )
        async with self._delivery_lock:
            try:
                event_id = await self._begin_event(context)
                key = f"{event_id}:{notification_fingerprint(message)}"
                if (
                    key not in self.pending
                    and key not in self.events[event_id]["delivered"]
                ):
                    await self.pending.set_and_save(
                        key,
                        {**message, "event_id": event_id, "created_at": time.time()},
                    )
                return await self._deliver(key, event_id)
            except OSError as error:
                raise NotificationStorageError(
                    "Cannot save the tracker alert or its delivery record."
                ) from error

    async def _deliver(
        self, key: str, event_id: str | None = None
    ) -> disnake.Message | None:
        message = self.pending.get(key)
        event_id = event_id or (
            message.get("event_id") if message is not None else None
        )
        if event_id is not None and key in self.events[event_id]["delivered"]:
            # Keep the receipt in memory if its previous save failed. Retry the
            # save before deleting the pending message, without sending again.
            await self.events.save()
            if message is not None:
                await self.pending.remove_and_save(key)
            await self._clean_event(event_id)
            return None
        if message is None:
            return None
        result = await delivery.send_to_channel(
            self.bot,
            message["channel_id"],
            message["content"],
            thread_id=message["thread_id"],
            embeds=[disnake.Embed.from_dict(embed) for embed in message["embeds"]],
        )
        if result is not None:
            if event_id is not None:
                event = self.events[event_id]
                self.events.data = {
                    **self.events.data,
                    event_id: {**event, "delivered": [*event["delivered"], key]},
                }
                await self.events.save()
        elif time.time() - message.get("created_at", 0) > self.max_age:
            # Messages saved before created_at existed count as expired.
            logger.error(
                "Dropped an alert for channel %s or thread %s after %s failed sends.",
                message["channel_id"],
                message["thread_id"],
                self._failures.get(key, 0) + 1,
            )
        else:
            failures = self._failures.get(key, 0)
            self._failures[key] = failures + 1
            self._retry_at[key] = time.monotonic() + min(
                self.retry_delay * 2 ** min(failures, 10), self.max_retry_delay
            )
            return None
        self._failures.pop(key, None)
        self._retry_at.pop(key, None)
        await self.pending.remove_and_save(key)
        if event_id is not None:
            await self._clean_event(event_id)
        return result

    async def _clean_event(self, key: str) -> None:
        if self.events[key]["complete"] and not any(
            message.get("event_id") == key for message in self.pending.values()
        ):
            await self.events.remove_and_save(key)

    async def flush(self, *, due_only: bool = False) -> None:
        """Send the pending messages. With due_only, skip those still waiting."""
        async with self._delivery_lock:
            now = time.monotonic()
            for key in list(self.pending):
                if due_only and self._retry_at.get(key, 0) > now:
                    continue
                await self._deliver(key)
            for key in list(self.events):
                await self._clean_event(key)

    async def run(self) -> None:
        while True:
            try:
                await self.flush(due_only=True)
            except Exception:
                logger.exception("Cannot deliver pending tracker alerts.")
            await asyncio.sleep(15)
