from disnake.ext.commands import InteractionBot
from aiohttp import BasicAuth

from scrts import (
    BOT_TOKEN,
    MONGODB_URI,
    HYPIXEL_API_KEY,
    PROXY_AUTH,
    PROXY,
    MINEFLAYER_EMAIL
)


# Credit Footer
OWNER_PFP: str = "https://github.com/RagingEnby/SkypixelRepo/blob/main/pfp.png?raw=true"
CREDIT_FOOTERS: set[str] = {
    "Made by @ragingenby",
    "Join my server! discord.gg/DdukMeYNdQ",
    "Support me on Patreon! patreon.com/RagingEnby"
}

# Discord ID's
OWNER_ID: int = 447861538095759365
DEV_SERVER_ID: int = 1066589212348006401
JOIN_LOG_CHANNEL: int = 1340389033951629525
ERROR_LOG_CHANNEL: int = 1131089040733634560
INVITE_LOG_CHANNEL: int = 1150164916578299945
COMMAND_LOG_CHANNEL: int = 1111050267975221326
DM_LOG_CHANNEL: int = 1173328319320698941
## AH Trackers
ADMIN_SPAWNED_ITEMS_CHANNEL: int = 1359366355819823334
OG_REFORGES_CHANNEL: int = 1359367040091295854
SEMI_OG_REFORGES_CHANNEL: int = 1359367058009358536
POI_AUCTIONS_CHANNEL: int = 1359374618946699504
OLD_ITEM_AUCTIONS_CHANNEL: int = 1359377036111511732
SEYMOUR_AUCTIONS_CHANNEL: int = 1360000687668334792
EXOTIC_AUCTIONS_CHANNEL: int = 1362226845696917555
EDITIONED_AUCTIONS_CHANNEL: int = 1366804475628486757
CAKE_SOUL_AUCTIONS_CHANNEL: int = 1365795200235999413
CHEAP_RED_SOUL_ROLE: int = 1366215277834014721
CHEAP_SOUL_ROLE: int = 1366217072346136688
EXOTIC_AUCTIONS_THREADS_PARENT: int = 1362450259120357396
EXOTIC_AUCTIONS_THREADS: dict['ExoticType', int] = { # type: ignore[name-defined]
    "crystal": 1362450340443848826,
    "og_fairy": 1362450421377011902,
    "fairy": 1362450389684850839,
    "spook": 1362450548862746634,
    "bleached": 1362450614273048797,
    "glitched": 1362451100615315576,
    "exotic": 1362451141782409417
}
## Misc Trackers
VERSION_TRACKER_CHANNELS: dict[int, str] = {
    1172205656112123994: "<@&1139315700339593256>", # RagingEnby's Dev Server
    1210333444563935295: "",                        # Derailcord
    1391179788164530276: "<@&1400911988305039370>", # Soul Hunters & Co.
}
MOTD_TRACKER_CHANNELS: dict[int, str] = {
    1177121432820527144: "<@&1177330036664193084>", # RagingEnby's Dev Server
    1177328270006554826: "<@&1177329389550178354>", # Derailcord
    1391179788164530276: "",                        # Soul Hunters & Co.
}
FIRE_SALE_TRACKER_CHANNELS: dict[int, str] = {
    1179543769905893416: "<@&1190093109938368552>", # RagingEnby's Dev Server
    1190098169703448576: "use code rail :)",        # Derailcord
    938088437200846948: "<@&937729428430151770>",   # Collector's Hub
    1314670732374180013: "",                        # Collector's Cafe
    1399601296931164252: "<@&1399600281422921777> use code yadi :)", # Yadi | Official Discord
    1391179788164530276: "",                        # Soul Hunters & Co.
}
ALPHA_TRACKER_CHANNELS: dict[int, str] = {
    1210999395865202688: "<@&1358904280165126434>", # RagingEnby's Dev Server
    1210333444563935295: "",                        # Derailcord
    1382202837856944289: "",                        # Kathund's Test Server
    1391179788164530276: "<@&1400910798368407712>", # Soul Hunters & Co.
}
ZONE_TRACKER_CHANNELS: dict[int, str] = {
    1256334830048903198: "<@&1210085254635724840>", # RagingEnby's Dev Server
    1210333444563935295: "",                        # Derailcord
    1391179788164530276: "",                        # Soul Hunters & Co.
}
WIKI_TRACKER_CHANNELS: dict[int, str] = {
    1287466083267121162: "", # RagingEnby's Dev Server
}
RANK_TRACKER_CHANNELS: dict[str, dict[int, str]] = {
    "youtube": {
        1121130539097784401: "<@&1122272183733977249>",  # RagingEnby's Dev Server
        1173855870568902747: "<@&1177329153607991428>",  # Derailcord
        1365021125628919898: "<@&1400910189678301276>",  # Soul Hunters & Co.
    },
    "staff": {
        1364997652323897415: "<@&1122272183733977249>", # RagingEnby's Dev Server
        1173855870568902747: "<@&1177329153607991428>", # Derailcord
        1365021125628919898: "<@&1400910189678301276>", # Soul Hunters & Co.
    },
    "special": {
        1269021624338878464: "<@&1122272183733977249>", # RagingEnby's Dev Server
        1173855870568902747: "<@&1177329153607991428>", # Derailcord
        1365021125628919898: "<@&1400910189678301276>", # Soul Hunters & Co.
    }
}

# Constants
## Random URL's
ITEM_IMAGE: str = "https://sky.shiiyu.moe/api/item/{}"
LEATHER_IMAGE: str = "https://api.ragingenby.dev/leather/{}/{}.png"
MC_HEAD_IMAGE: str = "https://cravatar.eu/helmavatar/{}/600.png"
MC_TEXT_IMAGE: str = "https://api.ragingenby.dev/render.png?text={}"
AUCTION_URL: str = "https://sky.coflnet.com/auction/{}"
STATS_URL: str = "https://sky.shiiyu.moe/stats/{}"
## Color-related stuff
COLOR_CODES: dict[str, int] = { # all minecraft color codes and their hex code
    "0": 0x000000, "1": 0x0000AA, "2": 0x00AA00,
    "3": 0x00AAAA, "4": 0xAA0000, "5": 0xAA00AA,
    "6": 0xFFAA00, "7": 0xAAAAAA, "8": 0x555555,
    "9": 0x5555FF, "a": 0x55FF55, "b": 0x55FFFF,
    "c": 0xFF5555, "d": 0xFF55FF, "e": 0xFFFF55,
    "f": 0xFFFFFF
}
COLOR_CODE_NAMES: dict[str, str] = { # all minecraft color codes and their official name
    "black": '0', "dark_blue": '1',
    "dark_green": '2', "cyan": '3',
    "dark_red": '4', "purple": '5',
    "gold": '6', "gray": '7',
    "dark_gray": '8', "blue": '9',
    "green": 'a', "aqua": 'b',
    "red": 'c', "pink": 'd',
    "yellow": 'e', "white": 'f'
}
DEFAULT_EMBED_COLOR: int = COLOR_CODES['2']
RARITY_COLORS: dict[str, int] = {
    "COMMON": COLOR_CODES['f'],
    "UNCOMMON": COLOR_CODES['a'],
    "RARE": COLOR_CODES['9'],
    "EPIC": COLOR_CODES['5'],
    "LEGENDARY": COLOR_CODES['6'],
    "MYTHIC": COLOR_CODES['d'],
    "DIVINE": COLOR_CODES['b'],
    "SPECIAL": COLOR_CODES['c'],
    "VERY_SPECIAL": COLOR_CODES['c'],
    "ULTIMATE": COLOR_CODES['4'],
    "ADMIN": COLOR_CODES['4']
}
RANK_COLORS: dict[str, int] = {
    "youtube": COLOR_CODES['c'],
    "staff": COLOR_CODES['c'],
    "owner": COLOR_CODES['c'],
    "pig_plus_plus_plus": COLOR_CODES['d'],
    "innit": COLOR_CODES['d'],
    "innit_plus": COLOR_CODES['d'], # future rank for if TommyInnit gets a netflix special
    "events": COLOR_CODES['6'],
    "mojang": COLOR_CODES['6'],
    "mcp": COLOR_CODES['c']
}
MINECRAFT_DYES: dict[int, dict[str, str | int]] = {
    0: {
        "item": "Ink Sac",
        "colorName": "black",
        "hex": 0x1D1D21,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/black.png?raw=true"
    },
    1: {
        "item": "Rose Red",
        "colorName": "red",
        "hex": 0xB02E26,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/red.png?raw=true"
    },
    2: {
        "item": "Cactus Green",
        "colorName": "dark green",
        "hex": 0x5E7C16,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/green.png?raw=true"
    },
    3: {
        "item": "Cocoa Beans",
        "colorName": "brown",
        "hex": 0x835432,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/brown.png?raw=true"
    },
    4: {
        "item": "Lapis Lazuli",
        "colorName": "dark blue",
        "hex": 0x3C44AA,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/blue.png?raw=true"
    },
    5: {
        "item": "Purple Dye",
        "colorName": "purple",
        "hex": 0x8932B8,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/purple.png?raw=true"
    },
    6: {
        "item": "Cyan Dye",
        "colorName": "cyan",
        "hex": 0x169C9C,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/cyan.png?raw=true"
    },
    7: {
        "item": "Light Gray Dye",
        "colorName": "light gray",
        "hex": 0x9D9D97,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/light_gray.png?raw=true"
    },
    8: {
        "item": "Gray Dye",
        "colorName": "gray",
        "hex": 0x474F52,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/gray.png?raw=true"
    },
    9: {
        "item": "Pink Dye",
        "colorName": "pink",
        "hex": 0xF38BAA,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/pink.png?raw=true"
    },
    10: {
        "item": "Lime Dye",
        "colorName": "lime green",
        "hex": 0x80C71F,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/lime.png?raw=true"
    },
    11: {
        "item": "Dandelion Yellow",
        "colorName": "yellow",
        "hex": 0xFED83D,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/yellow.png?raw=true"
    },
    12: {
        "item": "Light Blue Dye",
        "colorName": "light blue",
        "hex": 0x3AB3DA,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/light_blue.png?raw=true"
    },
    13: {
        "item": "Magenta Dye",
        "colorName": "magenta",
        "hex": 0xC74EBD,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/magenta.png?raw=true"
    },
    14: {
        "item": "Orange Dye",
        "colorName": "orange",
        "hex": 0xF9801D,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/orange.png?raw=true"
    },
    15: {
        "item": "Bone Meal",
        "colorName": "white",
        "hex": 0xF9FFFE,
        "image": "https://github.com/RagingEnby/SkypixelRepo/blob/main/cakesouls/images/white.png?raw=true"
    }
}
## Misc
SEYMOUR_IDS: dict[str, 'ArmorType'] = { # type: ignore
    "VELVET_TOP_HAT": "helmet",
    "CASHMERE_JACKET": "chestplate",
    "SATIN_TROUSERS": "leggings",
    "OXFORD_SHOES": "boots"
}
FAIRY_IDS: dict[str, 'ArmorType'] = { # type: ignore
    "FAIRY_HELMET": "helmet",
    "FAIRY_CHESTPLATE": "chestplate",
    "FAIRY_LEGGINGS": "leggings",
    "FAIRY_BOOTS": "boots"
}
CRYSTAL_IDS: set[str] = {
    "CRYSTAL_HELMET", "CRYSTAL_CHESTPLATE",
    "CRYSTAL_LEGGINGS", "CRYSTAL_BOOTS"
}
SPOOK_IDS: set[str] = {
    "GREAT_SPOOK_HELMET", "GREAT_SPOOK_CHESTPLATE",
    "GREAT_SPOOK_LEGGINGS", "GREAT_SPOOK_BOOTS"
}
ADMIN_ORIGIN_TAGS: set[str] = {"ITEM_MENU", "ITEM_COMMAND"}
OG_REFORGES: set[str] = {
    "forceful", "strong", "hurtful",
    "demonic", "rich", "odd"
}


# This is overwritten by main.py
BOT: InteractionBot
# Load Secrets (only here so IDE's don't get confused)
BOT_TOKEN: str = BOT_TOKEN
MONGODB_URI: str = MONGODB_URI
HYPIXEL_API_KEY: str = HYPIXEL_API_KEY
