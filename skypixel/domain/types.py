from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

# A MongoDB document or query. BSON values have many types (ObjectId,
# datetime, nested documents), and PyMongo itself types documents this way.
type Document = dict[str, Any]
# A MongoDB regex condition, such as {"$regex": "..."} or {"$not": {...}}.
type RegexQuery = dict[str, str] | dict[str, dict[str, str]]

# A value parsed from JSON text.
type JSON = dict[str, JSON] | list[JSON] | str | int | float | bool | None
# A value that can be written as JSON. Mapping and Sequence are read-only, so a
# dict[str, int] or a list[str] fits here where it would not fit JSON.
type JSONInput = (
    Mapping[str, JSONInput] | Sequence[JSONInput] | str | int | float | bool | None
)

ArmorType = Literal["helmet", "chestplate", "leggings", "boots"]

ExoticType = Literal[
    "exotic", "crystal", "fairy", "og_fairy", "spook", "bleached", "glitched"
]

PrefixRank = Literal[
    "NON",
    "[VIP]",
    "[VIP+]",
    "[MVP]",
    "[MVP+]",
    "[MVP++]",
    "[YOUTUBE]",
    "[PIG+++]",
    "[INNIT]",
    "[MAYOR]",
    "[MOJANG]",
    "[EVENTS]",
    "[HELPER]",
    "[MOD]",
    "[GM]",
    "[ADMIN]",
    "[OWNER]",
    "[ዞ]",
]


class Dye(TypedDict):
    item: str
    colorName: str
    hex: int
    image: str


SpecialRank = Literal[
    "youtube", "staff", "pig_plus_plus_plus", "innit", "events", "mojang", "mcp"
]
