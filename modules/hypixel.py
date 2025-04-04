from typing import Any
import requests


ITEMS: list[dict[str, Any]] = requests.get('https://api.ragingenby.dev/skyblock/items').json()['items']


def get_material(item_id: str) -> str:
    for item in ITEMS:
        if item_id == item.get('id'):
            if item.get('material'):
                return item['material']
            raise ValueError(f"No material found for {item['id']}: {item}")
    raise KeyError(item_id)
    