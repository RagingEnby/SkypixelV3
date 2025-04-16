from disnake.ext.commands import InteractionBot

from scrts import (
    BOT_TOKEN,
    MONGODB_URI,
    HYPIXEL_API_KEY
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
JOIN_LOG_CHANNEL: int = 1359945232946303016
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
## Misc Trackers
VERSION_TRACKER_CHANNELS: dict[int, str] = {
    1256322077825437756: "<@&1139315700339593256>", # RagingEnby's Dev Server
}
MOTD_TRACKER_CHANNELS: dict[int, str] = {
    1256322740541980803: "<@&1177330036664193084>", # RagingEnby's Dev Server
}
FIRE_SALE_TRACKER_CHANNELS: dict[int, str] = {
    1256327593200980029: "<@&1190093109938368552>", # RagingEnby's Dev Server
}
ALPHA_TRACKER_CHANNELS: dict[int, str] = {
    1256338710971158659: "<@&1358904280165126434>", # RagingEnby's Dev Server
}
ZONE_TRACKER_CHANNELS: dict[int, str] = {
    1256334830048903198: "<@&1210085254635724840>", # RagingEnby's Dev Server
}
WIKI_TRACKER_CHANNELS: dict[int, str] = {
    1287466083267121162: "", # RagingEnby's Dev Server
}
API_POLICY_TRACKER_CHANNELS: dict[int, str] = {
    1361432641286439052: "", # RagingEnby's Dev Server
}
RANK_TRACKER_CHANNELS: dict[str, dict[int, str]] = {
    "admin": {
        1269021399985422468: "<@&1122272183733977249>", # RagingEnby's Dev Server
    },
    "gm": {
        1269021571897491690: "<@&1122272183733977249>", # RagingEnby's Dev Server
    },
    "youtube": {
        1269021598447571168: "<@&1122272183733977249>", # RagingEnby's Dev Server
    },
    "special": {
        1269021624338878464: "<@&1122272183733977249>", # RagingEnby's Dev Server
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
    "admin": COLOR_CODES['c'],
    "gm": COLOR_CODES['2'],
    "owner": COLOR_CODES['c'],
    "pig_plus_plus_plus": COLOR_CODES['d'],
    "innit": COLOR_CODES['d'],
    "innit_plus": COLOR_CODES['d'], # future rank for if TommyInnit gets a netflix special
    "events": COLOR_CODES['6'],
    "mojang": COLOR_CODES['6'],
    "mcp": COLOR_CODES['c']
}
## Misc
SEYMOUR_IDS: dict[str, 'ArmorType'] = { # type: ignore
    "VELVET_TOP_HAT": "helmet",
    "CASHMERE_JACKET": "chestplate",
    "SATIN_TROUSERS": "leggings",
    "OXFORD_SHOES": "boots"
}


# This is overwritten by main.py
BOT: InteractionBot
# Load Secrets (only here so IDE's don't get confused)
BOT_TOKEN: str = BOT_TOKEN
MONGODB_URI: str = MONGODB_URI
HYPIXEL_API_KEY: str = HYPIXEL_API_KEY
