import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class CredentialFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[redacted]")
        record.msg = message
        record.args = ()
        return True


def configure_logging(storage_dir: Path, *, secrets: tuple[str, ...] = ()) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s:%(levelname)s:%(name)s:%(lineno)d] %(message)s"
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
        handler.addFilter(CredentialFilter(secrets))
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
    discord_handler.addFilter(CredentialFilter(secrets))
    discord_handler._skypixel_handler = True
    discord_logger.addHandler(discord_handler)
    discord_logger.propagate = False
