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


def _remove_own_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_skypixel_handler", False):
            logger.removeHandler(handler)
            handler.close()


def _file_handler(path: Path) -> RotatingFileHandler:
    return RotatingFileHandler(
        path, maxBytes=10_000_000, backupCount=3, encoding="utf-8"
    )


def configure_logging(storage_dir: Path, *, secrets: tuple[str, ...] = ()) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter(
        "[%(asctime)s:%(levelname)s:%(name)s:%(lineno)d] %(message)s", secrets
    )
    root = logging.getLogger()
    # Libraries such as PyMongo log every command at DEBUG, which would rotate
    # skypixel.log within minutes. Only the bot's own loggers record DEBUG.
    root.setLevel(logging.INFO)
    logging.getLogger("skypixel").setLevel(logging.DEBUG)
    disnake_logger = logging.getLogger("disnake")
    # DEBUG records every gateway payload and fills 10 MB in about 2.5 hours.
    disnake_logger.setLevel(logging.INFO)
    disnake_logger.propagate = False
    _remove_own_handlers(root)
    _remove_own_handlers(disnake_logger)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    for logger, handler in (
        (root, _file_handler(storage_dir / "skypixel.log")),
        (root, console_handler),
        (disnake_logger, _file_handler(storage_dir / "disnake.log")),
    ):
        handler.setFormatter(formatter)
        handler._skypixel_handler = True
        logger.addHandler(handler)
