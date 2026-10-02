import time
from typing import Any

from skypixel.domain.items import search_souls_query
from skypixel.storage.mongo import Collection


def soul_rank_pipeline(query: dict) -> list[dict]:
    pipeline = [
        {"$match": query},
        {
            "$addFields": {
                "cleaned_player_name": {
                    "$let": {
                        "vars": {
                            "parts": {
                                "$split": ["$extraAttributes.captured_player", "§"]
                            }
                        },
                        "in": {
                            "$reduce": {
                                "input": {
                                    "$slice": ["$$parts", 1, {"$size": "$$parts"}]
                                },
                                "initialValue": {"$arrayElemAt": ["$$parts", 0]},
                                "in": {
                                    "$concat": [
                                        "$$value",
                                        {
                                            "$substrCP": [
                                                "$$this",
                                                1,
                                                {
                                                    "$subtract": [
                                                        {"$strLenCP": "$$this"},
                                                        1,
                                                    ]
                                                },
                                            ]
                                        },
                                    ]
                                },
                            }
                        },
                    }
                }
            }
        },
        {
            "$addFields": {
                "captured_rank": {
                    "$let": {
                        "vars": {"words": {"$split": ["$cleaned_player_name", " "]}},
                        "in": {
                            "$cond": {
                                "if": {"$gte": [{"$size": "$$words"}, 2]},
                                "then": {"$arrayElemAt": ["$$words", 0]},
                                "else": "NON",
                            }
                        },
                    }
                }
            }
        },
        {"$group": {"_id": "$captured_rank", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "ranks": {"$push": {"k": "$_id", "v": "$count"}}}},
        {"$replaceRoot": {"newRoot": {"$arrayToObject": "$ranks"}}},
    ]
    return pipeline


class ItemRepository(Collection):
    cache_ttl = 300
    cache_limit = 512

    def __init__(self):
        super().__init__("SkyBlock", "itemdb")
        self.cache: dict[str, dict[str, Any]] = {}
        self._cached_at: dict[str, float] = {}

    def cache_items(self, items: list[dict[str, Any]]) -> None:
        now = time.monotonic()
        for item in items:
            uuid = item["_id"]
            self.cache.pop(uuid, None)
            self.cache[uuid] = item
            self._cached_at[uuid] = now
        while len(self.cache) > self.cache_limit:
            uuid = next(iter(self.cache))
            del self.cache[uuid]
            self._cached_at.pop(uuid, None)

    async def get_item(self, uuid: str) -> dict[str, Any] | None:
        if (
            uuid in self.cache
            and time.monotonic() - self._cached_at.get(uuid, 0) < self.cache_ttl
        ):
            return self.cache[uuid]
        self.cache.pop(uuid, None)
        self._cached_at.pop(uuid, None)
        item = await self.find_one({"_id": uuid})
        if item:
            self.cache_items([item])
        return item

    async def search_souls(self, query: dict) -> dict[str, int]:
        cursor = self.collection.aggregate(
            soul_rank_pipeline(search_souls_query(query))
        )
        results = await cursor.to_list(length=1)
        return results[0] if results else {}
