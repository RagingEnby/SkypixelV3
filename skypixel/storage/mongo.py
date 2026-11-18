import asyncio
import logging
from typing import Any

from pymongo import AsyncMongoClient, UpdateOne
from pymongo.errors import BulkWriteError

logger = logging.getLogger(__name__)


async def flush_queue(collection: Collection, queue: list[dict[str, Any]]) -> None:
    while queue:
        batch = queue[:1000]
        try:
            await collection.update_many(batch)
        except BulkWriteError as error:
            # The batch is unordered, so MongoDB wrote every document it did not
            # reject. Retrying would only repeat the rejected documents forever.
            write_errors = error.details.get("writeErrors", [])
            if not write_errors:
                raise
            logger.error(
                "MongoDB rejected %s documents in %s: %s",
                len(write_errors),
                getattr(collection, "collection_name", "a collection"),
                [batch[e["index"]].get("_id") for e in write_errors[:10]],
            )
        del queue[: len(batch)]


# One client per URI. Each client keeps its own connection pool and monitor
# threads, so the collections share one instead of opening four.
_clients: dict[str, AsyncMongoClient] = {}
_users: dict[str, int] = {}


def _acquire_client(uri: str) -> AsyncMongoClient:
    if uri not in _clients:
        _clients[uri] = AsyncMongoClient(uri, serverSelectionTimeoutMS=10000)
    _users[uri] = _users.get(uri, 0) + 1
    return _clients[uri]


async def _release_client(uri: str) -> None:
    _users[uri] -= 1
    if _users[uri] == 0:
        del _users[uri]
        await _clients.pop(uri).close()


class Collection:
    """Open the shared MongoDB connection when the collection is first used."""

    def __init__(self, uri: str, db: str, collection: str):
        self.uri = uri
        self.db_name = db
        self.collection_name = collection
        self._client = None
        self._closed = False

    @property
    def client(self):
        if self._closed:
            raise RuntimeError("The database collection has shut down.")
        if self._client is None:
            if not self.uri:
                raise ValueError("Set SKYPIXEL_MONGODB_URI or scrts.MONGODB_URI.")
            self._client = _acquire_client(self.uri)
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
        return await self.bulk_write(operations, ordered=False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        if client is not None:
            await _release_client(self.uri)
        logger.debug("Closed %s.%s", self.db_name, self.collection_name)

    async def search(
        self, query: dict, projection: dict | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("The search limit must be positive.")
        return await self.find(query, projection=projection).to_list(length=limit)


class UploadQueue:
    """Collect documents and upsert them into one collection in batches."""

    max_docs = 50_000

    def __init__(self, uri: str, db: str, collection: str):
        self.docs: list[dict[str, Any]] = []
        self.collection = Collection(uri, db, collection)
        self.dropped = 0
        self._flush_lock = asyncio.Lock()
        self._closed = False

    def append(self, doc: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("The upload queue has shut down.")
        # Drop new documents rather than old ones. A flush in progress removes
        # its batch from the front of the list by position.
        if len(self.docs) >= self.max_docs:
            if not self.dropped:
                logger.warning(
                    "The %s upload queue is full. Dropping new documents.",
                    self.collection.collection_name,
                )
            self.dropped += 1
            return
        self.docs.append(doc)

    async def flush(self) -> None:
        async with self._flush_lock:
            await flush_queue(self.collection, self.docs)
            if self.dropped:
                logger.warning(
                    "The %s upload queue dropped %s documents.",
                    self.collection.collection_name,
                    self.dropped,
                )
                self.dropped = 0

    async def close(self) -> None:
        async with self._flush_lock:
            if self._closed:
                return
            self._closed = True
            try:
                await flush_queue(self.collection, self.docs)
            finally:
                await self.collection.close()
