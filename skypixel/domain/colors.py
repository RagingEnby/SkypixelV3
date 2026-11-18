"""Classify armor colors using the rules from TGWaffles/iTEM."""

import logging
import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Literal

from skypixel import constants
from skypixel.clients.hypixel import SkyblockItem, item_id
from skypixel.domain import colorcompare
from skypixel.domain.types import ArmorType, ExoticType

logger: logging.Logger = logging.getLogger(__name__)

DYE_PATTERN: re.Pattern[str] = re.compile(
    r"Combinable in Anvil Changes the color of an armor piece to #([0-9A-Fa-f]{6})!"
)
CATEGORIES: dict[str, str] = {}
DEFAULT_HEXES: dict[str, str] = {}
MISC_HEXES: dict[str, str] = {
    "Bleached": "A06540",
    "Pure Red": "FF0000",
    "Pure Green": "00FF00",
    "Pure Yellow": "FFFF00",
    "Pure Cyan": "00FFFF",
    "Pure Pink": "FF00FF",
    "Pure White": "FFFFFF",
    "Pure Black": "000000",
    "Pure Blue": "0000FF",
}
CRYSTAL_COLORS: set[str] = {
    "1F0030",
    "46085E",
    "54146E",
    "5D1C78",
    "63237D",
    "6A2C82",
    "7E4196",
    "8E51A6",
    "9C64B3",
    "A875BD",
    "B88BC9",
    "C6A3D4",
    "D9C1E3",
    "E5D1ED",
    "EFE1F5",
    "FCF3FF",
}
FAIRY_COLORS: set[str] = {
    "330066",
    "4C0099",
    "660033",
    "660066",
    "6600CC",
    "7F00FF",
    "99004C",
    "990099",
    "9933FF",
    "B266FF",
    "CC0066",
    "CC00CC",
    "CC99FF",
    "E5CCFF",
    "FF007F",
    "FF00FF",
    "FF3399",
    "FF33FF",
    "FF66B2",
    "FF66FF",
    "FF99CC",
    "FF99FF",
    "FFCCE5",
    "FFCCFF",
}
OG_FAIRY_COLORS: set[str] = {
    "FF99FF",
    "FFCCFF",
    "E5CCFF",
    "CC99FF",
    "CC00CC",
    "FF00FF",
    "FF33FF",
    "FF66FF",
    "B266FF",
    "9933FF",
    "7F00FF",
    "660066",
    "6600CC",
    "4C0099",
    "330066",
    "990099",
}
SPOOK_COLORS: set[str] = {
    "000000",
    "070008",
    "0E000F",
    "150017",
    "1B001F",
    "220027",
    "29002E",
    "300036",
    "37003E",
    "3E0046",
    "45004D",
    "4C0055",
    "52005D",
    "590065",
    "60006C",
    "670074",
    "6E007C",
    "750084",
    "7C008B",
    "830093",
    "89009B",
    "9000A3",
    "9700AA",
    "993399",
    "9E00B2",
}
GLITCHED_COLORS: dict[str, str] = {
    "SHARK_SCALE": "FFDC51",
    "FROZEN_BLAZE": "F7DA33",
    "BAT_PERSON": "606060",
    "POWER_WITHER_CHESTPLATE": "E7413C",
    "TANK_WITHER_CHESTPLATE": "45413C",
    "SPEED_WITHER_CHESTPLATE": "4A14B7",
    "WISE_WITHER_CHESTPLATE": "1793C4",
    "WITHER_CHESTPLATE": "000000",
    "POWER_WITHER_LEGGINGS": "E75C3C",
    "TANK_WITHER_LEGGINGS": "65605A",
    "SPEED_WITHER_LEGGINGS": "5D2FB9",
    "WISE_WITHER_LEGGINGS": "17A8C4",
    "WITHER_LEGGINGS": "000000",
    "POWER_WITHER_BOOTS": "E76E3C",
    "TANK_WITHER_BOOTS": "88837E",
    "SPEED_WITHER_BOOTS": "8969C8",
    "WISE_WITHER_BOOTS": "1CD4E4",
    "WITHER_BOOTS": "000000",
}
VARIANT_COLORS: dict[str, set[str]] = {
    "RANCHERS_BOOTS": {"CC5500", "000000"},
    "REAPER_BOOTS": {"1B1B1B", "FF0000"},
    "REAPER_LEGGINGS": {"1B1B1B", "FF0000"},
    "REAPER_CHESTPLATE": {"1B1B1B", "FF0000"},
    "STARRED_ADAPTIVE_CHESTPLATE": {
        "3ABE78",
        "82E3D8",
        "BFBCB2",
        "D579FF",
        "FF4242",
        "FFC234",
    },
    "ADAPTIVE_CHESTPLATE": {"3ABE78", "82E3D8", "BFBCB2", "D579FF", "FF4242", "FFC234"},
    "STARRED_ADAPTIVE_LEGGINGS": {
        "169F57",
        "2AB5A5",
        "6E00A0",
        "BB0000",
        "BFBCB2",
        "FFF7E6",
    },
    "ADAPTIVE_LEGGINGS": {"169F57", "2AB5A5", "6E00A0", "BB0000", "BFBCB2", "FFF7E6"},
    "STARRED_ADAPTIVE_BOOTS": {
        "169F57",
        "2AB5A5",
        "6E00A0",
        "BB0000",
        "BFBCB2",
        "FFF7E6",
    },
    "ADAPTIVE_BOOTS": {"169F57", "2AB5A5", "6E00A0", "BB0000", "BFBCB2", "FFF7E6"},
}


for hex_code_ in sorted(CRYSTAL_COLORS):
    MISC_HEXES[f"Crystal #{hex_code_}"] = hex_code_
for hex_code_ in sorted(FAIRY_COLORS):
    MISC_HEXES[f"Fairy #{hex_code_}"] = hex_code_
for hex_code_ in sorted(OG_FAIRY_COLORS):
    MISC_HEXES[f"OG Fairy #{hex_code_}"] = hex_code_
for hex_code_ in sorted(SPOOK_COLORS):
    MISC_HEXES[f"Great Spook #{hex_code_}"] = hex_code_

OG_FAIRY: dict[ArmorType, list[str]] = {
    "helmet": ["FFCCE5", "FF99CC", "FF66B2"],
    "chestplate": ["660033", "FFCCE5", "FF99CC"],
    "leggings": ["660033", "99004C", "FFCCE5"],
    "boots": ["660033", "99004C", "CC0066"],
}

ARMOR_COLORS: dict[
    ArmorType | Literal["other"], dict[str, tuple[float, float, float]]
] = {
    "helmet": {},
    "chestplate": {},
    "leggings": {},
    "boots": {},
    "other": {k: colorcompare.hex_to_lab(v) for k, v in MISC_HEXES.items()},
}

for piece, hexes in OG_FAIRY.items():
    for hex_code_ in hexes:
        ARMOR_COLORS[piece][f"OG Fairy #{hex_code_}"] = colorcompare.hex_to_lab(
            hex_code_
        )


def configure(items: list[SkyblockItem]) -> None:
    """Build color tables after the item catalog loads."""
    CATEGORIES.clear()
    CATEGORIES.update(
        (item_id(item), category)
        for item in items
        if isinstance(category := item.get("category"), str)
    )
    DEFAULT_HEXES.clear()
    for armor_type, candidates in ARMOR_COLORS.items():
        candidates.clear()
        if armor_type == "other":
            candidates.update(
                (name, colorcompare.hex_to_lab(color))
                for name, color in MISC_HEXES.items()
            )
        else:
            candidates.update(
                (f"OG Fairy #{color}", colorcompare.hex_to_lab(color))
                for color in OG_FAIRY[armor_type]
            )
    for item in items:
        material = item.get("material")
        armor_type = (
            material.removeprefix("LEATHER_").lower()
            if isinstance(material, str) and material.startswith("LEATHER_")
            else None
        )
        if armor_type in ARMOR_COLORS and item.get("color"):
            try:
                color = item["color"]
                if not isinstance(color, str):
                    # A color that is not text has no split(), as before.
                    raise AttributeError("Invalid RGB color.")
                rgb = tuple(map(int, color.split(",")))
                if len(rgb) != 3 or any(value < 0 or value > 255 for value in rgb):
                    raise ValueError("Invalid RGB color.")
                DEFAULT_HEXES[item_id(item)] = colorcompare.rgb_to_hex(rgb)
                name = item.get("name", item_id(item))
                if isinstance(name, str):
                    ARMOR_COLORS[armor_type][name] = colorcompare.rgb_to_lab(rgb)
            except (ValueError, TypeError, AttributeError):  # fmt: skip
                logger.warning("Skipped an invalid default color for %s.", item["id"])
        description = item.get("description")
        dye = (
            DYE_PATTERN.fullmatch(description) if isinstance(description, str) else None
        )
        name = item.get("name", item_id(item))
        if item_id(item).startswith("DYE_") and dye and isinstance(name, str):
            ARMOR_COLORS["other"][name] = colorcompare.hex_to_lab(dye.group(1))
    find_closest_pieces.cache_clear()
    get_top_5.cache_clear()


def is_crystal(item_id: str, hex_code: str) -> bool:
    return hex_code in CRYSTAL_COLORS and item_id not in constants.CRYSTAL_IDS


def is_fairy(item_id: str, hex_code: str) -> bool:
    return hex_code in FAIRY_COLORS and item_id not in constants.FAIRY_IDS


def is_og_fairy(item_id: str, hex_code: str) -> bool:
    """Match iTEM's FairyColours.isOGFairyColour.

    Any piece can have an original fairy color. The other colors in each
    OG_FAIRY list were original only for that armor slot.
    """
    if hex_code in OG_FAIRY_COLORS:
        return True
    category = CATEGORIES.get(item_id, "")
    for armor_type in ("boots", "leggings", "chestplate", "helmet"):
        if armor_type.upper() in item_id or category == armor_type.upper():
            return hex_code in OG_FAIRY[armor_type]
    return False


def is_spook(item_id: str, hex_code: str) -> bool:
    return hex_code in SPOOK_COLORS and item_id not in constants.SPOOK_IDS


def is_bleached(hex_code: str) -> bool:
    return hex_code == MISC_HEXES["Bleached"]


def is_glitched(item_id: str, hex_code: str) -> bool:
    return GLITCHED_COLORS.get(item_id) == hex_code


def is_variant(item_id: str, hex_code: str) -> bool:
    if (
        item_id in constants.SEYMOUR_IDS
        or item_id.startswith("LEATHER_")
        or item_id == "GHOST_BOOTS"
        or hex_code == DEFAULT_HEXES.get(item_id)
        or hex_code in VARIANT_COLORS.get(item_id, ())
    ):
        return True

    if item_id in constants.FAIRY_IDS:
        return hex_code in FAIRY_COLORS

    if item_id in constants.CRYSTAL_IDS:
        return hex_code in CRYSTAL_COLORS

    if item_id in constants.SPOOK_IDS:
        return hex_code in SPOOK_COLORS

    return False


def get_exotic_type(
    item_id: str, hex_code: str, extra_attributes: Mapping[str, object] | None = None
) -> ExoticType | None:
    hex_code = hex_code.upper()
    if (extra_attributes and extra_attributes.get("dye_item")) or is_variant(
        item_id, hex_code
    ):
        return None
    if is_glitched(item_id, hex_code):
        return "glitched"
    if is_bleached(hex_code):
        return "bleached"
    if is_crystal(item_id, hex_code):
        return "crystal"
    if is_og_fairy(item_id, hex_code):
        return "og_fairy"
    if is_fairy(item_id, hex_code):
        return "fairy"
    if is_spook(item_id, hex_code):
        return "spook"
    return "exotic"


@lru_cache(maxsize=1024)
def find_closest_pieces(armor_type: ArmorType, color: str | int) -> dict[str, float]:
    lab = (
        colorcompare.hex_to_lab(color)
        if isinstance(color, str)
        else colorcompare.int_to_lab(color)
    )
    candidates = {**ARMOR_COLORS[armor_type], **ARMOR_COLORS["other"]}
    matches: dict[str, float] = {}
    for name, candidate_lab in candidates.items():
        matches[name] = colorcompare.compare_delta_cie(lab, candidate_lab)
    return dict(sorted(matches.items(), key=lambda item: item[1]))


@lru_cache(maxsize=1024)
def get_top_5(armor_type: ArmorType, color: str | int) -> dict[str, float]:
    top_5: dict[str, float] = {}
    groups: set[str] = set()
    for name, distance in find_closest_pieces(armor_type, color).items():
        if len(top_5) >= 5:
            break
        group = next(
            (group for group in ("Great Spook", "Crystal", "Fairy") if group in name),
            None,
        )
        if group is not None:
            if group in groups:
                continue
            groups.add(group)
        top_5[name] = distance
    return top_5
