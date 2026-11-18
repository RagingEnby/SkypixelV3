from typing import Literal, TypedDict

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
