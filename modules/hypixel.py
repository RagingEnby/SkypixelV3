import logging
from typing import Any, Literal

import requests

logger = logging.getLogger(__name__)

ITEMS: list[dict[str, Any]] = requests.get('https://api.ragingenby.dev/skyblock/items').json()['items']
MEMENTOS: list[str] = [i['id'] for i in ITEMS if i.get('category') == 'MEMENTO']

Memento = Literal[tuple(MEMENTOS)]  # type: ignore


def get_material(item_id: str) -> str:
    logger.debug(f"Attempting to find material for {item_id}")
    for item in ITEMS:
        if item_id == item.get('id'):
            logger.debug(f"Found item: {item}")
            if item.get('material'):
                logger.debug(f"Found material: {item['material']}")
                return item['material']
            logger.error(f"No material found for item id '{item_id}', raising ValueError()")
            raise ValueError(f"No material found for {item['id']}: {item}")
    logger.error(f"Invalid item_id: '{item_id}'- not found in item data. Raising KeyError()")
    raise KeyError(item_id)


def get_name(item_id: str) -> str:
    logger.debug(f"Attempting to find name for {item_id}")
    for item in ITEMS:
        if item_id == item.get('id'):
            logger.debug(f"Found item: {item}")
            if item.get('name'):
                logger.debug(f"Found name: {item['name']}")
                return item['name']
            logger.error(f"No name found for item id '{item_id}', raising ValueError()")
            raise ValueError(f"No name found for {item['id']}: {item}")
    logger.error(f"Invalid item_id: '{item_id}'- not found in item data. Raising KeyError()")
    raise KeyError(item_id)
