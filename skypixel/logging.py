import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: tuple[str, ...]):
        super().__init__(fmt)
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self.secrets)


def configure_logging(storage_dir: Path, *, secrets: tuple[str, ...] = ()) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    formatter = RedactingFormatter(
        "[%(asctime)s:%(levelname)s:%(name)s:%(lineno)d] %(message)s", secrets
    )
    for handler in list(root.handlers):
        if getattr(handler, "_skypixel_handler", False):
            root.removeHandler(handler)
            handler.close()
    file_handler = RotatingFileHandler(
        storage_dir / "skypixel.log",
        maxBytes=10_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler._skypixel_handler = True
        root.addHandler(handler)
    discord_logger = logging.getLogger("disnake")
    discord_logger.setLevel(logging.DEBUG)
    for handler in list(discord_logger.handlers):
        if getattr(handler, "_skypixel_handler", False):
            discord_logger.removeHandler(handler)
            handler.close()
    discord_handler = RotatingFileHandler(
        storage_dir / "disnake.log",
        maxBytes=10_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    discord_handler.setFormatter(formatter)
    discord_handler._skypixel_handler = True
    discord_logger.addHandler(discord_handler)
    discord_logger.propagate = False
