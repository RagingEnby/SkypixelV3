"""Shared clients that the cogs use, built once when the bot starts."""

import asyncio
from pathlib import Path

from skypixel.clients import http, hypixel, mojang
from skypixel.settings import Settings
from skypixel.storage.items import ItemRepository


class Services:
    """Hold the item database and own the lifecycle of the shared clients.

    The HTTP session, the Mojang player cache, and the item catalog still live
    in their modules, because many callers use the module functions. This
    object loads the catalog and closes every client on shutdown.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.item_db = ItemRepository(settings.mongodb_uri)
        self._closed = False

    async def load_catalog(self, storage_dir: Path) -> None:
        await hypixel.load_items(storage_dir)

    async def close(self) -> list[BaseException]:
        """Close every client and return the errors instead of raising them."""
        if self._closed:
            return []
        self._closed = True
        results = await asyncio.gather(
            self.item_db.close(),
            mojang.close(),
            http.close(),
            return_exceptions=True,
        )
        return [result for result in results if isinstance(result, BaseException)]
