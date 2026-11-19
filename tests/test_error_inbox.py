import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import tests.support  # noqa: F401
from skypixel import error_inbox

WEBHOOK: str = "https://relay.example/hooks/secret-path"


def make_record(
    message: str = "The poll failed.",
    error: BaseException | None = None,
    level: int = logging.ERROR,
    name: str = "skypixel.trackers.base",
) -> logging.LogRecord:
    exc_info: Any = (type(error), error, error.__traceback__) if error else None
    return logging.LogRecord(name, level, __file__, 55, message, (), exc_info)


def raised(error: BaseException) -> BaseException:
    try:
        raise error
    except BaseException as caught:
        return caught


class ErrorInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.handler: error_inbox.ErrorInboxHandler = error_inbox.ErrorInboxHandler(
            WEBHOOK, Path(self.tmp.name), ("bot-token",)
        )
        self.pending: Path = Path(self.tmp.name) / "pending"

    def reports(self) -> list[dict[str, Any]]:
        if not self.pending.exists():
            return []
        return [json.loads(path.read_text()) for path in sorted(self.pending.iterdir())]

    def test_writes_redacted_report(self) -> None:
        error: BaseException = raised(ValueError("bad bot-token response"))
        self.handler.handle(make_record(error=error))
        [report] = self.reports()
        self.assertEqual(report["source"], "skypixel.trackers.base:55")
        self.assertEqual(report["error"], "ValueError: bad [redacted] response")
        self.assertNotIn("bot-token", report["traceback"])
        self.assertIn("raise error", report["traceback"])

    def test_ignores_warnings(self) -> None:
        log: logging.Logger = logging.getLogger("skypixel.tests.inbox")
        log.addHandler(self.handler)
        self.addCleanup(log.removeHandler, self.handler)
        log.warning("Only a warning.")
        self.assertEqual(self.reports(), [])
        log.error("A real error.")
        self.assertEqual(len(self.reports()), 1)

    def test_skips_repeats_within_ten_minutes(self) -> None:
        with patch.object(error_inbox.time, "monotonic", return_value=5.0):
            self.handler.handle(make_record(error=raised(KeyError("a"))))
            self.handler.handle(make_record(error=raised(KeyError("a"))))
            self.handler.handle(make_record(error=raised(KeyError("b"))))
        self.assertEqual(len(self.reports()), 2)
        with patch.object(error_inbox.time, "monotonic", return_value=700.0):
            self.handler.handle(make_record(error=raised(KeyError("a"))))
        self.assertEqual(len(self.reports()), 3)

    def test_ignores_its_own_logger(self) -> None:
        self.handler.handle(make_record(name=error_inbox.logger.name))
        self.assertEqual(self.reports(), [])

    def test_posts_summary_from_event_loop(self) -> None:
        post: AsyncMock = AsyncMock()

        async def run() -> None:
            with patch.object(self.handler, "post", post):
                self.handler.handle(make_record(error=raised(RuntimeError("x"))))
                # A second error inside 30 seconds waits in pending/.
                self.handler.handle(make_record(error=raised(RuntimeError("y"))))
                await asyncio.gather(*self.handler._tasks)

        asyncio.run(run())
        self.assertEqual(len(self.reports()), 2)
        post.assert_awaited_once()
        payload, path = post.await_args.args
        self.assertEqual(payload["error"], "RuntimeError: x")
        self.assertTrue(path.exists())

    def test_post_sends_short_body(self) -> None:
        response: MagicMock = MagicMock()
        session: MagicMock = MagicMock()
        session.post = AsyncMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        payload: dict[str, Any] = {
            "id": "abc",
            "source": "skypixel.x:1",
            "error": "RuntimeError: x",
            "message": "failed",
        }
        with patch.object(error_inbox.curl_cffi, "AsyncSession", return_value=session):
            asyncio.run(self.handler.post(payload, Path("/tmp/report.json")))
        url, = session.post.await_args.args
        self.assertEqual(url, WEBHOOK)
        self.assertEqual(
            session.post.await_args.kwargs["json"],
            {
                "event": "skypixel_error",
                "id": "abc",
                "source": "skypixel.x:1",
                "summary": "RuntimeError: x",
                "report_file": "/tmp/report.json",
            },
        )

    def test_install_needs_a_webhook(self) -> None:
        self.assertIsNone(error_inbox.install("", Path(self.tmp.name)))

    def test_install_replaces_old_handler(self) -> None:
        root: logging.Logger = logging.getLogger()
        before: list[logging.Handler] = list(root.handlers)
        try:
            first = error_inbox.install(WEBHOOK, Path(self.tmp.name))
            second = error_inbox.install(WEBHOOK, Path(self.tmp.name))
            self.assertNotIn(first, root.handlers)
            self.assertIn(second, root.handlers)
            self.assertIn(second, logging.getLogger("disnake").handlers)
        finally:
            for target in (root, logging.getLogger("disnake")):
                for handler in list(target.handlers):
                    if isinstance(handler, error_inbox.ErrorInboxHandler):
                        target.removeHandler(handler)
            self.assertEqual(root.handlers, before)


if __name__ == "__main__":
    unittest.main()
