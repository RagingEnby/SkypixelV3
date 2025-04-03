from disnake.ext.commands import InteractionBot
from scrts import (
    BOT_TOKEN,
    MONGODB_URI,
    HYPIXEL_API_KEY
)

# Config Stuff
OWNER_ID: int = 447861538095759365


# Constants
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


# This is overwriten by main.py
BOT: InteractionBot
