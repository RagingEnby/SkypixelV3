import logging
from pathlib import Path
from typing import Any

from curl_cffi.requests.exceptions import RequestException

from skypixel.clients import http
from skypixel.storage.json import read_json, write_json

logger = logging.getLogger(__name__)
ITEMS_URL: str = http.API_URL + "/hypixel/skyblock/items"
FALLBACK_URL = "https://api.hypixel.net/v2/resources/skyblock/items"
ITEMS: list[dict[str, Any]] = []
MEMENTOS: list[str] = []
_items_by_id: dict[str, dict[str, Any]] = {}


def validate_items(data: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("items"), list)
        or not data["items"]
    ):
        raise ValueError("The item API did not return a nonempty items list.")
    items = data["items"]
    if any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str)
        for item in items
    ):
        raise ValueError("Each item needs a string id.")
    return items


def initialize(items: list[dict[str, Any]]) -> None:
    from skypixel.domain import colors

    validate_items({"items": items})
    ITEMS[:] = items
    MEMENTOS[:] = [item["id"] for item in items if item.get("category") == "MEMENTO"]
    _items_by_id.clear()
    _items_by_id.update((item["id"], item) for item in items)
    colors.configure(items)


async def load_items(storage_dir: Path) -> None:
    cache_path = storage_dir / "items.json"
    for url in (ITEMS_URL, FALLBACK_URL):
        try:
            items = validate_items(await http.get_json(url))
        except (RequestException, ValueError):  # fmt: skip
            logger.warning("Cannot load item data from %s.", url)
            continue
        initialize(items)
        try:
            await write_json(cache_path, {"items": items})
        except OSError:
            logger.exception("Cannot cache item data in %s.", cache_path)
        return
    try:
        items = validate_items(read_json(cache_path))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Cannot load item data from either API or the local cache."
        ) from error
    logger.warning("Both item APIs are unavailable. Using %s.", cache_path)
    initialize(items)


def _get_field(item_id: str, field: str) -> str:
    if item_id not in _items_by_id:
        raise KeyError(item_id)
    value = _items_by_id[item_id].get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Item {item_id} has no {field}.")
    return value


def get_material(item_id: str) -> str:
    return _get_field(item_id, "material")


def get_name(item_id: str) -> str:
    return _get_field(item_id, "name")
