"""Shared clients that the cogs use, built once when the bot starts."""

import asyncio
from pathlib import Path
from types import ModuleType

from skypixel.clients import http, hypixel, mojang
from skypixel.settings import Settings
from skypixel.storage.items import ItemRepository


class Services:
    """Hold the HTTP client, the item database, and the item catalog.

    The HTTP session, the Mojang player cache, and the catalog lists still
    live in their modules, because many callers use the module functions.
    This object owns their lifecycle: it loads the catalog and closes the
    clients on shutdown.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http: ModuleType = http
        self.catalog: ModuleType = hypixel
        self.item_db = ItemRepository(settings.mongodb_uri)
        self._closed = False

    async def load_catalog(self, storage_dir: Path) -> None:
        await self.catalog.load_items(storage_dir)

    async def close(self) -> list[BaseException]:
        """Close every client and return the errors instead of raising them."""
        if self._closed:
            return []
        self._closed = True
        results = await asyncio.gather(
            self.item_db.close(),
            mojang.close(),
            self.http.close(),
            return_exceptions=True,
        )
        return [result for result in results if isinstance(result, BaseException)]
