import os
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Self


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default="", repr=False)
    mongodb_uri: str = field(default="", repr=False)
    storage_dir: Path = Path("storage")

    @classmethod
    def load(cls) -> Self:
        try:
            legacy: ModuleType | None = import_module("scrts")
        except ModuleNotFoundError as error:
            if error.name != "scrts":
                raise
            legacy = None
        return cls(
            bot_token=os.environ.get(
                "SKYPIXEL_BOT_TOKEN", getattr(legacy, "BOT_TOKEN", "")
            ),
            mongodb_uri=os.environ.get(
                "SKYPIXEL_MONGODB_URI", getattr(legacy, "MONGODB_URI", "")
            ),
            storage_dir=Path(os.environ.get("SKYPIXEL_STORAGE_DIR", "storage")),
        )

    def validate(self) -> None:
        missing: list[str] = []
        if not self.bot_token:
            missing.append("SKYPIXEL_BOT_TOKEN or scrts.BOT_TOKEN")
        if not self.mongodb_uri:
            missing.append("SKYPIXEL_MONGODB_URI or scrts.MONGODB_URI")
        if missing:
            raise ConfigurationError(
                "Set the required credentials: " + ", ".join(missing)
            )
