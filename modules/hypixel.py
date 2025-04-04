from typing import Any, Literal
import requests


ITEMS: list[dict[str, Any]] = requests.get('https://api.ragingenby.dev/skyblock/items').json()['items']
MEMENTOS: list[str] = [i['id'] for i in ITEMS if i.get('category') == 'MEMENTO']

Memento = Literal[tuple(MEMENTOS)]  # type: ignore


def get_material(item_id: str) -> str:
    for item in ITEMS:
        if item_id == item.get('id'):
            if item.get('material'):
                return item['material']
            raise ValueError(f"No material found for {item['id']}: {item}")
    raise KeyError(item_id)
    