"""Send this app's errors to the shared T3 error inbox.

Canonical copy: ~/error-inbox/error_inbox_client.py on ragingserver. Do not
edit a vendored copy. Edit the canonical file, then run
`python3 ~/error-inbox/errorinbox.py sync` to copy it into every app.

The client only appends one JSON line per error to
``~/.cache/error-inbox/<app>/events.jsonl``. The error-inbox daemon reads that
file, groups repeats, writes the report files, and posts to the T3 webhook, so
the app never waits on the network. Standard library only.
"""

# Every app vendors this file byte for byte, so app formatters must leave it be.
# fmt: off

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

# The same error from the same place is written at most once per this many
# seconds. The daemon does the real grouping. This only keeps a tight error
# loop from filling the disk.
THROTTLE_SECONDS: float = 60
TRACEBACK_CHARS: int = 8000
MESSAGE_CHARS: int = 2000
# Pass as `extra=SKIP` on a log call whose error the app also sends with
# report(), so the inbox files it once, with the report's context.
SKIP: dict[str, bool] = {"error_inbox_skip": True}

_state: dict[str, Any] = {
    "app": None,
    "path": None,
    "commit": "unknown",
    "secrets": (),
    "redact": None,
}
_recent: dict[str, float] = {}
_lock: threading.Lock = threading.Lock()


def inbox_root() -> Path:
    return Path(
        os.environ.get("ERROR_INBOX_ROOT", Path.home() / ".cache" / "error-inbox")
    )


def _git_head(root: Path) -> str:
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%h %s"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except OSError:
        return "unknown"
    except subprocess.SubprocessError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _clean(text: str) -> str:
    for secret in _state["secrets"]:
        text = text.replace(secret, "[redacted]")
    redact: Callable[[str], str] | None = _state["redact"]
    if redact is not None:
        try:
            text = redact(text)
        except Exception:  # noqa: BLE001, RUF100 - never break the app
            # Never send text that may still hold a secret.
            text = "[redaction failed]"
    return text


def _format_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def report(
    source: str,
    error: BaseException | None = None,
    *,
    message: str | None = None,
    level: str = "ERROR",
    created: float | None = None,
    **context: object,
) -> None:
    """Record one error for the inbox. Never raises. Does nothing before install()."""
    app: str | None = _state["app"]
    path: Path | None = _state["path"]
    if app is None or path is None:
        return
    try:
        error_text: str | None = f"{type(error).__name__}: {error}" if error else None
        kind: str = type(error).__name__ if error else level
        detail: str = str(error) if error else message or ""
        key: str = f"{source}|{kind}|{detail[:160]}"
        now: float = time.monotonic()
        with _lock:
            last: float | None = _recent.get(key)
            if last is not None and now - last < THROTTLE_SECONDS:
                return
            _recent[key] = now
        event: dict[str, Any] = {
            "app": app,
            "created_at": datetime.fromtimestamp(
                created or time.time(), UTC
            ).isoformat(),
            "level": level,
            "source": source,
            "message": _clean(message or error_text or source)[:MESSAGE_CHARS],
            "error": _clean(error_text)[:MESSAGE_CHARS] if error_text else None,
            "traceback": _clean(_format_traceback(error))[-TRACEBACK_CHARS:]
            if error
            else None,
            "commit": _state["commit"],
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }
        if context:
            event["context"] = json.loads(_clean(json.dumps(context, default=str)))
        line: bytes = (json.dumps(event, default=str) + "\n").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        # One write() on an O_APPEND file, so lines from several processes
        # do not interleave. The file is reopened each time so the daemon can
        # rotate it.
        fd: int = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001, RUF100 - never break the app
        # The inbox must never break the app. Note it on stderr and move on.
        sys.stderr.write("error inbox: could not record an error\n")


class ErrorInboxHandler(logging.Handler):
    """Logging handler that records every ERROR or CRITICAL record."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "error_inbox_skip", False):
            return
        error: BaseException | None = record.exc_info[1] if record.exc_info else None
        try:
            message: str = record.getMessage()
        except Exception:  # noqa: BLE001, RUF100 - never break the app
            message = str(record.msg)
        report(
            f"{record.name}:{record.lineno}",
            error,
            message=message,
            level=record.levelname,
            created=record.created,
            function=record.funcName,
        )


def _install_hooks() -> None:
    if _state.get("hooked"):
        return
    _state["hooked"] = True
    previous_sys: Callable[
        [type[BaseException], BaseException, TracebackType | None], Any
    ] = sys.excepthook
    previous_thread: Callable[[threading.ExceptHookArgs], Any] = threading.excepthook

    def sys_hook(
        kind: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        if not issubclass(kind, KeyboardInterrupt):
            report(
                "uncaught",
                value.with_traceback(tb),
                message="Uncaught exception, the process is exiting.",
                level="CRITICAL",
            )
        previous_sys(kind, value, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            name: str = args.thread.name if args.thread else "unknown"
            report(
                f"thread:{name}",
                args.exc_value,
                message=f"Uncaught exception in thread {name}.",
            )
        previous_thread(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook


def install(
    app: str,
    *,
    project_root: Path | str,
    secrets: Iterable[Any] = (),
    redact: Callable[[str], str] | None = None,
    loggers: Iterable[str] = ("",),
    capture_logs: bool = True,
) -> ErrorInboxHandler | None:
    """Start recording errors for ``app``.

    ``secrets`` are exact strings to blank out. ``redact`` is an optional
    project redactor applied after that. With ``capture_logs`` the handler is
    attached to each logger in ``loggers`` ("" is the root logger). Without it,
    only report() calls and uncaught exceptions are recorded.
    Calling install() again replaces the earlier handler.
    """
    _state["app"] = app
    _state["path"] = inbox_root() / app / "events.jsonl"
    _state["commit"] = _git_head(Path(project_root))
    _state["secrets"] = tuple(
        str(value) for value in secrets if value and len(str(value)) >= 6
    )
    _state["redact"] = redact
    _install_hooks()
    if not capture_logs:
        return None
    handler: ErrorInboxHandler = ErrorInboxHandler(logging.ERROR)
    for name in loggers:
        target: logging.Logger = logging.getLogger(name)
        for old in [h for h in target.handlers if isinstance(h, ErrorInboxHandler)]:
            target.removeHandler(old)
        target.addHandler(handler)
    return handler
