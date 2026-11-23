import os
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

DEFAULT_API_URL: str = "http://127.0.0.1:8001"


class ConfigurationError(ValueError):
    pass


def load_api_url() -> str:
    """Return the RagingEnby API base URL from SKYPIXEL_API_URL.

    The HTTP client reads this at import time to build its URL constants, so
    it cannot wait for Settings.load().
    """
    return os.environ.get("SKYPIXEL_API_URL", DEFAULT_API_URL).rstrip("/")


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default="", repr=False)
    mongodb_uri: str = field(default="", repr=False)
    storage_dir: Path = Path("storage")
    api_url: str = DEFAULT_API_URL

    @classmethod
    def load(cls):
        try:
            legacy = import_module("scrts")
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
            api_url=load_api_url(),
        )

    def validate(self):
        missing = []
        if not self.bot_token:
            missing.append("SKYPIXEL_BOT_TOKEN or scrts.BOT_TOKEN")
        if not self.mongodb_uri:
            missing.append("SKYPIXEL_MONGODB_URI or scrts.MONGODB_URI")
        if missing:
            raise ConfigurationError(
                "Set the required credentials: " + ", ".join(missing)
            )
        if not self.api_url.startswith(("http://", "https://")):
            raise ConfigurationError(
                "SKYPIXEL_API_URL must start with http:// or https://."
            )
