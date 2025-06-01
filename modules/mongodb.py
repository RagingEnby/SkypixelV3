import logging
from typing import Any

import motor.motor_asyncio as motor

import constants

logger = logging.getLogger(__name__)


class Collection:
    def __init__(self, db: str, collection: str):
        self.db_name = db
        self.collection_name = collection

        self.client = motor.AsyncIOMotorClient(constants.MONGODB_URI)
        self.db = self.client[self.db_name]
        self.collection = self.db[self.collection_name]
        self.find = self.collection.find
        self.find_one = self.collection.find_one
        self.count_documents = self.collection.count_documents
        self.insert_many = self.collection.insert_many
        self.bulk_write = self.collection.bulk_write

    async def close(self):
        logger.info(f"Closing {self.db_name}.{self.collection_name}")
        return self.client.close()

    async def search(self, query: dict, projection: dict | None = None, limit: int = 50) -> list[dict[str, Any]]:
        logger.debug(f"Searching {self.db_name}.{self.collection_name} for {query}")
        cursor = self.find(query, projection=projection)
        return await cursor.to_list(length=limit)
