# this is honestly some of the worse/messiest code in this bot lmao
# its lowkey just roughly stolen from TGWaffles/iTEM but badly converted to Python

import logging
import re
from functools import lru_cache
from typing import Literal

import requests

import constants
from modules import colorcompare

logger = logging.getLogger(__name__)

DYE_PATTERN = re.compile(r"Combinable in Anvil Changes the color of an armor piece to #([0-9A-Fa-f]+)!")
ArmorType = Literal['helmet', 'chestplate', 'leggings', 'boots']
ExoticType = Literal['exotic', 'crystal', 'fairy', 'og_fairy', 'spook', 'bleached', 'glitched']
try:
    ITEMS = requests.get('https://api.ragingenby.dev/skyblock/items').json()['items']
except:
    logger.warning("WARNING: USING HYPIXEL ITEMS ENDPOINT, api.ragingenby.dev IS DOWN")
    ITEMS = requests.get('https://api.hypixel.net/v2/resources/skyblock/items').json()['items']
DEFAULT_HEXES: dict[str, str] = {
    i['id']: colorcompare.rgb_to_hex(tuple(map(int, i['color'].split(','))))  # type: ignore
    for i in ITEMS if i.get('id') and i.get('color') and i['material'].startswith('LEATHER_')
}
MISC_HEXES = {
    "Bleached": "A06540",
    "Pure Red": "FF0000",
    "Pure Green": "00FF00",
    "Pure Yellow": "FFFF00",
    "Pure Cyan": "00FFFF",
    "Pure Pink": "FF00FF",
    "Pure White": "FFFFFF",
    "Pure Black": "000000",
    "Pure Blue": "0000FF"
}
CRYSTAL_COLORS = {"1F0030", "46085E", "54146E", "5D1C78", "63237D", "6A2C82", "7E4196", "8E51A6", "9C64B3", "A875BD",
                  "B88BC9", "C6A3D4", "D9C1E3", "E5D1ED", "EFE1F5", "FCF3FF"}
FAIRY_COLORS = {"330066", "4C0099", "660033", "660066", "6600CC", "7F00FF", "99004C", "990099", "9933FF", "B266FF",
                "CC0066", "CC00CC", "CC99FF", "E5CCFF", "FF007F", "FF00FF", "FF3399", "FF33FF", "FF66B2", "FF66FF",
                "FF99CC", "FF99FF", "FFCCE5", "FFCCFF"}
OG_FAIRY_COLORS = {"FF99FF", "FFCCFF", "E5CCFF", "CC99FF", "CC00CC", "FF00FF", "FF33FF", "FF66FF",
                  "B266FF", "9933FF", "7F00FF", "660066", "6600CC", "4C0099", "330066", "990099"}
SPOOK_COLORS = {"000000", "070008", "0E000F", "150017", "1B001F", "220027", "29002E", "300036",
                "37003E", "3E0046","45004D", "4C0055", "52005D", "590065", "60006C", "670074",
                "6E007C", "750084", "7C008B", "830093","89009B", "9000A3", "9700AA", "993399", "9E00B2"}
GLITCHED_COLORS = {
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
    "WITHER_BOOTS": "000000"
}
VARIANT_COLORS = {
    "RANCHERS_BOOTS": {"CC5500", "000000"},
    "REAPER_BOOTS": {"1B1B1B", "FF0000"},
    "REAPER_LEGGINGS": {"1B1B1B", "FF0000"},
    "REAPER_CHESTPLATE": {"1B1B1B", "FF0000"},
    "STARRED_ADAPTIVE_CHESTPLATE": {"3ABE78", "82E3D8", "BFBCB2", "D579FF", "FF4242", "FFC234"},
    "ADAPTIVE_CHESTPLATE": {"3ABE78", "82E3D8", "BFBCB2", "D579FF", "FF4242", "FFC234"},
    "STARRED_ADAPTIVE_LEGGINGS": {"169F57", "2AB5A5", "6E00A0", "BB0000", "BFBCB2", "FFF7E6"},
    "ADAPTIVE_LEGGINGS": {"169F57", "2AB5A5", "6E00A0", "BB0000", "BFBCB2", "FFF7E6"},
    "STARRED_ADAPTIVE_BOOTS": {"169F57", "2AB5A5", "6E00A0", "BB0000", "BFBCB2", "FFF7E6"},
    "ADAPTIVE_BOOTS": {"169F57", "2AB5A5", "6E00A0", "BB0000", "BFBCB2", "FFF7E6"}
}


for hex_code_ in CRYSTAL_COLORS:
    MISC_HEXES[f"Crystal #{hex_code_}"] = hex_code_
for hex_code_ in FAIRY_COLORS:
    MISC_HEXES[f"Fairy #{hex_code_}"] = hex_code_
for hex_code_ in OG_FAIRY_COLORS:
    MISC_HEXES[f"OG Fairy #{hex_code_}"] = hex_code_
for hex_code_ in SPOOK_COLORS:
    MISC_HEXES[f"Great Spook #{hex_code_}"] = hex_code_

OG_FAIRY: dict[ArmorType, list[str]] = {
    "helmet": ["FFCCE5", "FF99CC", "FF66B2"],
    "chestplate": ["660033", "FFCCE5", "FF99CC"],
    "leggings": ["660033", "99004C", "FFCCE5"],
    "boots": ["660033", "99004C", "CC0066"],
}

ARMOR_COLORS: dict[ArmorType | Literal['other'], dict[str, tuple[float, float, float]]] = {
    "helmet": {},
    "chestplate": {},
    "leggings": {},
    "boots": {},
    "other": {k: colorcompare.hex_to_lab(v) for k, v in MISC_HEXES.items()},
}

for piece, hexes in OG_FAIRY.items():
    for hex_code_ in hexes:
        ARMOR_COLORS[piece][f"OG Fairy #{hex_code_}"] = colorcompare.hex_to_lab(hex_code_)

for item_ in ITEMS:
    armor_type_ = item_['material'].replace('LEATHER_', '').lower() if item_['material'].startswith('LEATHER_') else None
    if armor_type_ and item_.get('color'):
        r, g, b = item_['color'].split(',')
        rgb = (int(r), int(g), int(b))
        ARMOR_COLORS[armor_type_][item_['name']] = colorcompare.rgb_to_lab(rgb)
    dye_match = DYE_PATTERN.fullmatch(item_['description']) if item_.get('description') else None
    if item_['id'].startswith('DYE_') and dye_match:
        ARMOR_COLORS['other'][item_['name']] = colorcompare.hex_to_lab(dye_match.group(1))


def is_crystal(item_id: str, hex_code: str) -> bool:
    return hex_code in CRYSTAL_COLORS and item_id not in constants.CRYSTAL_IDS


def is_fairy(item_id: str, hex_code: str) -> bool:
    return hex_code in FAIRY_COLORS and item_id not in constants.FAIRY_IDS


def is_og_fairy(item_id: str, hex_code: str) -> bool:
    return hex_code in OG_FAIRY.get(constants.FAIRY_IDS.get(item_id), [])


def is_spook(item_id: str, hex_code: str) -> bool:
    return hex_code in SPOOK_COLORS and item_id not in constants.SPOOK_IDS


def is_bleached(hex_code: str) -> bool:
    return hex_code == MISC_HEXES['Bleached']


def is_glitched(item_id: str, hex_code: str) -> bool:
    return GLITCHED_COLORS.get(item_id) == hex_code


def is_variant(item_id: str, hex_code: str) -> bool:
    if any([
        item_id in constants.SEYMOUR_IDS,
        item_id.startswith('LEATHER_'),
        item_id == "GHOST_BOOTS",
        hex_code == DEFAULT_HEXES.get(item_id),
        hex_code in VARIANT_COLORS.get(item_id, [])
    ]):
        return True

    if item_id in constants.FAIRY_IDS:
        return hex_code in FAIRY_COLORS

    if item_id in constants.CRYSTAL_IDS:
        return hex_code in CRYSTAL_COLORS

    if item_id in constants.SPOOK_IDS:
        return hex_code in SPOOK_COLORS

    return False


def get_exotic_type(item_id: str, hex_code: str, extra_attributes: dict | None = None) -> ExoticType | None:
    hex_code = hex_code.upper()
    if (extra_attributes and extra_attributes.get('dye_item')) or is_variant(item_id, hex_code):
        return None
    if is_glitched(item_id, hex_code):
        return 'glitched'
    if is_bleached(hex_code):
        return 'bleached'
    if is_crystal(item_id, hex_code):
        return 'crystal'
    if is_og_fairy(item_id, hex_code):
        return 'og_fairy'
    if is_fairy(item_id, hex_code):
        return 'fairy'
    if is_spook(item_id, hex_code):
        return 'spook'
    return 'exotic'


@lru_cache(maxsize=None)
def find_closest_pieces(armor_type: ArmorType, color: str | int) -> dict[str, float]:
    lab = colorcompare.hex_to_lab(color) if isinstance(color, str) else colorcompare.int_to_lab(color)
    candidates = ARMOR_COLORS[armor_type.lower()] # type: ignore
    candidates.update(ARMOR_COLORS['other'])
    matches = {}
    for name, candidate_lab in candidates.items():
        #matches[name] = colorcompare.compare_delta_e_2000(lab, candidate_lab)
        matches[name] = colorcompare.compare_delta_cie(lab, candidate_lab)
    # sort matches by lowest closest to farthest
    return {k: v for k, v in sorted(matches.items(), key=lambda item: item[1])}


@lru_cache(maxsize=None)
def get_top_5(armor_type: ArmorType, color: str | int) -> dict[str, float]:
    data = find_closest_pieces(armor_type, color)
    top_5 = {}
    fairy = False
    crystal = False
    great_spook = False
    for k, v in data.items():
        if len(top_5) >= 5:
            break
        if 'Great Spook' in k:
            if not great_spook:
                great_spook = True
                top_5[k] = v
            continue
        elif 'Crystal' in k:
            if not crystal:
                crystal = True
                top_5[k] = v
            continue
        elif 'Fairy' in k:
            if not fairy:
                fairy = True
                top_5[k] = v
            continue
        top_5[k] = v
    return top_5
