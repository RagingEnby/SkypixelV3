"""Send every bot error to the T3 Code error inbox.

A logging handler catches each ERROR record, writes a full report to
``<inbox>/pending/`` and posts a short notice to a T3 webhook. The scheduled
task behind the webhook reads the pending files.
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import curl_cffi
from curl_cffi.requests.exceptions import RequestException

from skypixel.logging import redact

logger: logging.Logger = logging.getLogger(__name__)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
EVENT: str = "skypixel_error"
# Report the same error at most once per 10 minutes.
MIN_SIGNATURE_SECONDS: float = 600
# Post at most once per 30 seconds. Reports written in between wait in
# pending/ until the next post.
MIN_POST_SECONDS: float = 30
POST_ATTEMPTS: int = 3


def git_head(root: Path = PROJECT_ROOT) -> str:
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%h %s"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def signature(record: logging.LogRecord) -> str:
    error: BaseException | None = record.exc_info[1] if record.exc_info else None
    name: str = type(error).__name__ if error else "no exception"
    message: str = str(error) if error else record.getMessage()
    return f"{record.name}:{record.lineno}|{name}|{message[:160]}"


class ErrorInboxHandler(logging.Handler):
    def __init__(
        self, webhook: str, inbox_dir: Path, secrets: tuple[str, ...] = ()
    ) -> None:
        super().__init__(logging.ERROR)
        self.webhook: str = webhook
        self.pending_dir: Path = inbox_dir / "pending"
        self.secrets: tuple[str, ...] = tuple(
            secret for secret in (*secrets, webhook) if secret
        )
        self.commit: str = git_head()
        self._recent: dict[str, float] = {}
        self._last_post: float | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        # The inbox logs its own delivery problems. Reporting those would loop.
        if record.name == logger.name:
            return
        try:
            key: str = signature(record)
            now: float = time.monotonic()
            # The monotonic clock can start near zero at boot, so a missing
            # entry must not read as "seen at time 0".
            last_seen: float | None = self._recent.get(key)
            if last_seen is not None and now - last_seen < MIN_SIGNATURE_SECONDS:
                return
            self._recent[key] = now
            payload: dict[str, Any] = self.build(record)
            path: Path = self.write(payload)
            if self._last_post is not None and now - self._last_post < MIN_POST_SECONDS:
                return
            try:
                loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
            except RuntimeError:
                # No event loop, so the report waits in pending/ for the next post.
                return
            self._last_post = now
            task: asyncio.Task[None] = loop.create_task(
                self.post(payload, path), name="skypixel-error-inbox"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception:
            self.handleError(record)

    def build(self, record: logging.LogRecord) -> dict[str, Any]:
        error: BaseException | None = record.exc_info[1] if record.exc_info else None
        created: datetime = datetime.fromtimestamp(record.created, UTC)
        return {
            "id": uuid.uuid4().hex,
            "created_at": created.isoformat(),
            "source": f"{record.name}:{record.lineno}",
            "message": redact(record.getMessage(), self.secrets),
            "error": (
                redact(f"{type(error).__name__}: {error}", self.secrets)
                if error
                else None
            ),
            "traceback": (
                redact("".join(traceback.format_exception(error)), self.secrets)[
                    -4000:
                ]
                if error
                else None
            ),
            "bot_commit": self.commit,
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }

    def write(self, payload: dict[str, Any]) -> Path:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        stamp: str = datetime.fromisoformat(payload["created_at"]).strftime(
            "%Y%m%dT%H%M%S"
        )
        path: Path = self.pending_dir / f"{stamp}-{payload['id']}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    async def post(self, payload: dict[str, Any], path: Path) -> None:
        body: dict[str, str] = {
            "event": EVENT,
            "id": payload["id"],
            "source": payload["source"],
            "summary": payload["error"] or payload["message"],
            "report_file": str(path),
        }
        # The bot's shared HTTP session closes at shutdown, which is when late
        # errors still need to go out, so the inbox uses its own session.
        async with curl_cffi.AsyncSession(timeout=15) as session:
            for attempt in range(POST_ATTEMPTS):
                try:
                    response: curl_cffi.Response = await session.post(
                        self.webhook, json=body
                    )
                    response.raise_for_status()
                    return
                except RequestException:
                    if attempt == POST_ATTEMPTS - 1:
                        logger.warning(
                            "Could not send error report %s to the inbox.",
                            payload["id"],
                        )
                        return
                    await asyncio.sleep(2**attempt)


def install(
    webhook: str, inbox_dir: Path, secrets: tuple[str, ...] = ()
) -> ErrorInboxHandler | None:
    """Attach the inbox to the root and disnake loggers. Does nothing without a webhook."""
    if not webhook:
        return None
    handler: ErrorInboxHandler = ErrorInboxHandler(webhook, inbox_dir, secrets)
    # configure_logging removes handlers marked like this when it runs again.
    handler._skypixel_handler = True
    for target in (logging.getLogger(), logging.getLogger("disnake")):
        for old in [h for h in target.handlers if isinstance(h, ErrorInboxHandler)]:
            target.removeHandler(old)
        target.addHandler(handler)
    return handler
