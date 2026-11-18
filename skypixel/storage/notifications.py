import asyncio
import logging
import time
from contextlib import suppress

import disnake

from skypixel.storage.database import Database, PendingAlert

logger = logging.getLogger(__name__)


class Outbox:
    """Send the alerts that trackers saved in the database with their state.

    A tracker poll saves its new state and its alerts in one transaction (see
    TrackerState.replace). run() then sends each saved alert and marks it
    sent. Alerts for one channel or thread go out in the order they were
    saved. Different channels are sent at the same time.

    Delivery is at least once. If the bot stops after Discord accepts a
    message but before the database marks it sent, the next start sends that
    message again. A message repeats at most once this way. If marking a
    message sent fails while the bot keeps running, the outbox remembers the
    message and retries the mark without sending it again.

    A message that cannot be sent is retried after 15 seconds, then after
    twice as long each time, up to 15 minutes. After max_age seconds it is
    marked dead and an error is logged, so a deleted channel cannot hold a
    message forever. Sent and dead messages are deleted after a week.
    """

    max_age = 6 * 60 * 60
    retry_delay = 15
    max_retry_delay = 15 * 60
    poll_interval = 15
    keep_finished = 7 * 24 * 60 * 60

    def __init__(self, bot: disnake.Client, database: Database):
        self.bot = bot
        self.database = database
        self._lock = asyncio.Lock()
        # Messages Discord accepted whose sent mark failed to save.
        self._sent: dict[int, float] = {}

    async def flush(self, *, due_only: bool = True) -> None:
        """Send the saved messages. Without due_only, ignore retry delays."""
        async with self._lock:
            for alert_id, sent_at in list(self._sent.items()):
                await self.database.mark_sent(alert_id, sent_at)
                del self._sent[alert_id]
            now = time.time()
            pending = await self.database.due_alerts(now if due_only else float("inf"))

            # due_alerts() returns rows in id order, and each group keeps it.
            groups: dict[tuple[int, int | None], list[PendingAlert]] = {}
            for row in pending:
                key = (row.alert.channel_id, row.alert.thread_id)
                groups.setdefault(key, []).append(row)
            results = await asyncio.gather(
                *(self._deliver_all(rows) for rows in groups.values()),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            await self.database.prune(now - self.keep_finished)

    async def _deliver_all(self, rows: list[PendingAlert]) -> None:
        for row in rows:
            await self._deliver(row)

    async def _deliver(self, row: PendingAlert) -> None:
        from skypixel import utils

        alert = row.alert
        result = await utils.send_to_channel(
            self.bot,
            alert.channel_id,
            alert.content,
            thread_id=alert.thread_id,
            embeds=[disnake.Embed.from_dict(embed) for embed in alert.embeds],
        )
        now = time.time()
        attempts = row.attempts + 1
        if result is not None:
            self._sent[row.id] = now
            await self.database.mark_sent(row.id, now)
            del self._sent[row.id]
        elif now - row.created_at > self.max_age:
            logger.error(
                "Dropped an alert for channel %s or thread %s after %s failed sends.",
                alert.channel_id,
                alert.thread_id,
                attempts,
            )
            await self.database.mark_dead(row.id, attempts)
        else:
            delay = min(
                self.retry_delay * 2 ** min(row.attempts, 10), self.max_retry_delay
            )
            await self.database.mark_failed(row.id, attempts, now + delay)

    async def run(self) -> None:
        saved = self.database.alerts_saved
        while True:
            saved.clear()
            try:
                await self.flush()
            except Exception:
                logger.exception("Cannot deliver pending tracker alerts.")
            with suppress(TimeoutError):
                await asyncio.wait_for(saved.wait(), self.poll_interval)
