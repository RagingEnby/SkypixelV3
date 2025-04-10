from typing import Any

import motor.motor_asyncio as motor

import constants


class Collection:
    def __init__(self, db: str, collection: str):
        self.db_name = db
        self.collection_name = collection

        self.client = motor.AsyncIOMotorClient(constants.MONGODB_URI)
        self.db = self.client[self.db_name]
        self.collection = self.db[self.collection_name]
        self.find = self.collection.find
        self.find_one = self.collection.find_one

    async def close(self):
        return self.client.close()

    async def search(self, query: dict, projection: dict | None = None, limit: int = 50) -> list[dict[str, Any]]:
        cursor = self.find(query, projection=projection)
        return await cursor.to_list(length=limit)
