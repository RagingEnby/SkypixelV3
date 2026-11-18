# What Is Skypixel
Skypixel is a Discord bot I have worked on and off on for a couple years now. It's made to assist with item collecting in Hypixel SkyBlock.

Originally, Skypixel was made as a frontend to search through spreadsheets from [iTEM](https://tem.cx/) in the same style as [TEMBot](https://discord.com/users/937105508320546896)'s `/spook-search` command. However, over time it evolved into much more.

# Running it
Skypixel needs [uv](https://docs.astral.sh/uv/), a Discord bot token, and a MongoDB database.

1. Set `SKYPIXEL_BOT_TOKEN` and `SKYPIXEL_MONGODB_URI`, or copy `scrts.py.example` to `scrts.py` and fill it in.
2. Run `uv run main.py`.

The bot keeps its state and logs in `storage/`. Set `SKYPIXEL_STORAGE_DIR` to use another folder.

The channel and role IDs in `skypixel/constants.py` belong to the live bot's servers. Change them before you run your own copy.

`config/subscriptions.toml` lists the channels that receive each alert and the ping sent with it. Edit it and restart the bot to add or remove a subscriber. Set `SKYPIXEL_SUBSCRIPTIONS` to read the list from another file. The bot refuses to start if an entry is malformed, and logs a warning at startup for each listed channel it cannot find or post embeds in.

# Checks
```sh
uv run ruff check .
uv run ruff format --check .
uv run python -W error::ResourceWarning -m unittest discover -s tests -t .
```

# History
- SkypixelV1 was HORRIBLY coded with abysmal performance, near constant crashes, and a level beyond spaghetti code.
- SkypixelV2 was never finished as I lost interest before finishing it. Then, upon coming back to it, I realized just how bad the code was again!
- SkypixelV3 is, hopefully, the final full recode of Skypixel made to fix all of these problems.

# Future
- Implement a mineflayer bot to monitor when alpha opens/closes and when the kick message changes
- Eventually, I will make SkypixelV4 which will be done fully in GOLANG.

# Thanks to...
- [iTEM](https://tem.cx/) for supplying much of the data used for the item database module of Skypixel and its owner [TGWaffles](https://github.com/TGWaffles/) for creating it
- [artificialair](https://github.com/artificialair/) for helping me a LOT in the __EARLY__ days of Skypixel when I was just getting back into development and was very bad at it
- [Antisniper](https://api.antisniper.net/) for supplying the initial rank tracker data
- [matdev](https://matdoes.dev/) for supplying a [VERY large Minecraft player database](https://matdoes.dev/minecraft-uuids) used in the bots backend
- [Hypixel](https://api.hypixel.net/) for making this project possible

# License
Skypixel is licensed under the [GNU Affero General Public License v3.0](LICENSE). You may change and sell the code, but anything you build from it, including a hosted copy of the bot, must be released under the same license with its source.
