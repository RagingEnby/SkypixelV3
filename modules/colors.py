# this is honestly some of the worse/messiest code in this bot lmao

from typing import Literal
import requests
from functools import lru_cache
import re

from modules import colorcompare

DYE_PATTERN = re.compile(r"Combinable in Anvil Changes the color of an armor piece to #([0-9A-Fa-f]+)!")
ArmorType = Literal['helmet', 'chestplate', 'leggings', 'boots']

try:
    ITEMS = requests.get('https://api.ragingenby.dev/skyblock/items').json()['items']
except:
    print("WARNING: USING HYPIXEL ITEMS ENDPOINT, api.ragingenby.dev IS DOWN")
    ITEMS = requests.get('https://api.hypixel.net/v2/resources/skyblock/items').json()['items']

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
CRYSTAL_COLORS = ["1F0030", "46085E", "54146E", "5D1C78", "63237D", "6A2C82", "7E4196", "8E51A6", "9C64B3", "A875BD",
                 "B88BC9", "C6A3D4", "D9C1E3", "E5D1ED", "EFE1F5", "FCF3FF"]
FAIRY_COLORS = ["330066", "4C0099", "660033", "660066", "6600CC", "7F00FF", "99004C", "990099", "9933FF", "B266FF",
               "CC0066", "CC00CC", "CC99FF", "E5CCFF", "FF007F", "FF00FF", "FF3399", "FF33FF", "FF66B2", "FF66FF",
               "FF99CC", "FF99FF", "FFCCE5", "FFCCFF"]
OG_FAIRY_COLORS = ["FF99FF", "FFCCFF", "E5CCFF", "CC99FF", "CC00CC", "FF00FF", "FF33FF", "FF66FF",
                  "B266FF", "9933FF", "7F00FF", "660066", "6600CC", "4C0099", "330066", "990099"]
SPOOK_COLORS = ["000000", "070008", "0E000F", "150017", "1B001F", "220027", "29002E", "300036",
                "37003E", "3E0046","45004D", "4C0055", "52005D", "590065", "60006C", "670074",
                "6E007C", "750084", "7C008B", "830093","89009B", "9000A3", "9700AA", "993399", "9E00B2"]
for hex_code in CRYSTAL_COLORS:
    MISC_HEXES[f"Crystal #{hex_code}"] = hex_code
for hex_code in FAIRY_COLORS:
    MISC_HEXES[f"Fairy #{hex_code}"] = hex_code
for hex_code in OG_FAIRY_COLORS:
    MISC_HEXES[f"OG Fairy #{hex_code}"] = hex_code
for hex_code in SPOOK_COLORS:
    MISC_HEXES[f"Great Spook #{hex_code}"] = hex_code

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
    for hex in hexes:
        ARMOR_COLORS[piece][f"OG Fairy #{hex}"] = colorcompare.hex_to_lab(hex)

for item in ITEMS:
    armor_type = item['material'].replace('LEATHER_', '').lower() if item['material'].startswith('LEATHER_') else None
    if armor_type and item.get('color'):
        r, g, b = item['color'].split(',')
        rgb = (int(r), int(g), int(b))
        ARMOR_COLORS[armor_type][item['name']] = colorcompare.rgb_to_lab(rgb)
    dye_match = DYE_PATTERN.fullmatch(item['description']) if item.get('description') else None
    if item['id'].startswith('DYE_') and dye_match:
        ARMOR_COLORS['other'][item['name']] = colorcompare.hex_to_lab(dye_match.group(1))


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
