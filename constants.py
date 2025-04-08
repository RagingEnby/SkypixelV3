from disnake.ext.commands import InteractionBot
from scrts import (
    BOT_TOKEN,
    MONGODB_URI,
    HYPIXEL_API_KEY
)

# Config Stuff
OWNER_ID: int = 447861538095759365
OWNER_PFP: str = "https://github.com/RagingEnby/SkypixelRepo/blob/main/pfp.png?raw=true"

CREDIT_FOOTERS: set[str] = {
    "Made by @ragingenby",
    "Join my server! discord.gg/DdukMeYNdQ",
    "Support me on Patreon! patreon.com/RagingEnby"
}

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
ITEM_IMAGE: str = "https://sky.shiiyu.moe/api/item/{}"
LEATHER_IMAGE: str = "https://api.tem.cx/leather/{}/{}"
MC_HEAD_IMAGE: str = "https://cravatar.eu/helmavatar/{}/600.png"
MC_TEXT_IMAGE: str = "https://api.ragingenby.dev/render.png?text={}"
DEFAULT_EMBED_COLOR: int = 0x00AA00
RARITY_COLORS: dict[str, int] = {
  "COMMON": 16777215,
  "UNCOMMON": 5635925,
  "RARE": 5592575,
  "EPIC": 11141290,
  "LEGENDARY": 16755200,
  "MYTHIC": 16733695,
  "DIVINE": 5636095,
  "SUPREME": 5636095,
  "SPECIAL": 16733525,
  "VERY_SPECIAL": 16733525,
  "ADMIN": 11141120
}
RANK_COLORS: dict[str, int] = {
    "youtube": 0xFF5555,
    "admin": 0xFF5555,
    "gm": 0x00AA00,
    "owner": 0xFF5555,
    "pig_plus_plus_plus": 0xFF55FF,
    "innit": 0xFF55FF,
    "innit_plus": 0xFF55FF,
    "events": 0xFFAA00,
    "mojang": 0xFFAA00,
    "mcp": 0xFF5555
}


# This is overwriten by main.py
BOT: InteractionBot
