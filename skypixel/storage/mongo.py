import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

from skypixel.settings import settings

logger = logging.getLogger(__name__)


async def flush_queue(collection: "Collection", queue: list[dict[str, Any]]) -> None:
    while queue:
        batch = queue[:1000]
        await collection.update_many(batch)
        del queue[: len(batch)]


class Collection:
    """Open a MongoDB connection when the collection is first used."""

    def __init__(self, db: str, collection: str):
        self.db_name = db
        self.collection_name = collection
        self._client = None
        self._closed = False

    @property
    def client(self):
        if self._closed:
            raise RuntimeError("The database collection has shut down.")
        if self._client is None:
            if not settings.mongodb_uri:
                raise ValueError("Set SKYPIXEL_MONGODB_URI or scrts.MONGODB_URI.")
            self._client = AsyncIOMotorClient(
                settings.mongodb_uri, serverSelectionTimeoutMS=10000
            )
        return self._client

    @property
    def db(self):
        return self.client[self.db_name]

    @property
    def collection(self):
        return self.db[self.collection_name]

    def find(self, *args, **kwargs):
        return self.collection.find(*args, **kwargs)

    async def find_one(self, *args, **kwargs):
        return await self.collection.find_one(*args, **kwargs)

    async def count_documents(self, *args, **kwargs):
        return await self.collection.count_documents(*args, **kwargs)

    async def insert_many(self, *args, **kwargs):
        return await self.collection.insert_many(*args, **kwargs)

    async def bulk_write(self, *args, **kwargs):
        return await self.collection.bulk_write(*args, **kwargs)

    async def update_many(self, docs: list[dict[str, Any]]):
        if not docs:
            return None
        operations = [
            UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {key: value for key, value in doc.items() if key != "_id"}},
                upsert=True,
            )
            for doc in docs
        ]
        return await self.bulk_write(operations)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            self._client.close()
            self._client = None
        logger.debug("Closed %s.%s", self.db_name, self.collection_name)

    async def search(
        self, query: dict, projection: dict | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("The search limit must be positive.")
        return await self.find(query, projection=projection).to_list(length=limit)
