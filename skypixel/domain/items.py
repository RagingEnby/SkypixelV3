import logging
import re
from typing import Any

from skypixel import constants, utils
from skypixel.domain.types import PrefixRank

logger = logging.getLogger(__name__)


def fix_item(item: dict[str, Any]) -> dict[str, Any]:
    """Repair old owner and timestamp fields before displaying an item."""
    item = item.copy()
    if not isinstance(item.get("previousOwners"), list):
        item["previousOwners"] = []
    if "createdAt" in item:
        item["created_at"] = item.pop("createdAt")
    for field in ("lastChecked", "start", "created_at"):
        if isinstance(item.get(field), dict):
            item[field] = 0
    if (
        isinstance(item.get("created_at"), int)
        and abs(item["created_at"]) < 100_000_000_000
    ):
        item["created_at"] *= 1000
    return item


def get_item_image(item: dict[str, Any]) -> str:
    return utils.get_item_image(
        item_id=item["itemId"],
        color=item.get("colour"),
        durability=item.get("extraAttributes", {}).get("soul_durability"),
    )


def get_item_color(item: dict[str, Any]) -> int:
    if item.get("colour"):
        return int(item["colour"], 16)
    soul_durability = item.get("extraAttributes", {}).get("soul_durability")
    if item["itemId"] == "CAKE_SOUL" and soul_durability in constants.MINECRAFT_DYES:
        return constants.MINECRAFT_DYES[soul_durability]["hex"]
    return constants.RARITY_COLORS.get(
        item.get("rarity") or "", constants.DEFAULT_EMBED_COLOR
    )


def make_playername_regex(playername: str) -> dict[str, str]:
    color_code_pattern = "(§[0-9a-fk-or])*"
    escaped_name = re.escape(playername)
    return {"$regex": f"(§7| ){escaped_name}{color_code_pattern}$", "$options": "i"}


def make_rank_regex(rank: PrefixRank) -> dict:
    if rank == "NON":
        return {"$not": {"$regex": " "}}
    color_code_pattern = "(§[0-9a-fk-or])*"
    escaped_rank_chars = [re.escape(char) for char in rank]
    interspersed_rank = color_code_pattern.join(escaped_rank_chars)
    return {"$regex": f"^{color_code_pattern}{interspersed_rank}"}


def make_player_regex(
    rank: PrefixRank | None = None, playername: str | None = None
) -> dict[str, Any]:
    if playername and rank:
        # The stored text is the rank, a space, and the name, with color codes
        # anywhere between. A player without a rank is stored as §7 and the name.
        color_code_pattern = "(§[0-9a-fk-or])*"
        name = f"{re.escape(playername)}{color_code_pattern}$"
        if rank == "NON":
            return {"$regex": f"^[^ ]*§7{name}", "$options": "i"}
        prefix = color_code_pattern.join(re.escape(char) for char in rank)
        return {
            "$regex": f"^{color_code_pattern}{prefix}.*(§7| ){name}",
            "$options": "i",
        }
    if playername:
        return make_playername_regex(playername)
    if rank:
        return make_rank_regex(rank)
    raise ValueError("Provide a player name or a rank.")


def search_souls_query(query: dict) -> dict:
    query = {k: v for k, v in query.items() if v is not None}
    query["itemId"] = "CAKE_SOUL"
    if not query.get("extraAttributes.captured_player"):
        query["extraAttributes.captured_player"] = {"$exists": True}
    return query
