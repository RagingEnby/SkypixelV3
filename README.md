# What Is Skypixel
Skypixel is a Discord bot I have worked on and off on for a couple years now. It's made to assist with item collecting in Hypixel SkyBlock.

Originally, Skypixel was made as a frontend to search through spreadsheets from [iTEM](https://tem.cx/) in the same style as [TEMBot](https://discord.com/users/937105508320546896)'s `/spook-search` command. However, over time it evolved into much more.

# Configuration
The bot reads these environment variables:
- `SKYPIXEL_BOT_TOKEN` and `SKYPIXEL_MONGODB_URI` are required. A `scrts.py` file with `BOT_TOKEN` and `MONGODB_URI` also works (see `scrts.py.example`).
- `SKYPIXEL_STORAGE_DIR` is the data folder. The default is `storage`.
- `SKYPIXEL_API_URL` is the RagingEnby API. The default is `http://127.0.0.1:8001`, which skips Cloudflare when the bot runs on the same host as the API.

To pause Discord output, create an empty file named `muted` in the storage folder. Tracker alerts wait in the outbox and go out after you delete the file. Other messages, such as guild join logs, are skipped while the file exists.

# History
- SkypixelV1 was HORRIBLY coded with abysmal performance, near constant crashes, and a level beyond spagetti code.
- SkypixelV2 was never finished as I lost interest before finishing it. Then, upon coming back to it, I realized just how bad the code was again!
- SkypixelV3 is, hopefully, the final full recode of Skypixel made to fix all of these problems.

# Future
- Impliment a mineflayer bot to monitor when alpha opens/closes and when the kick message changes
- Eventually, I will make SkypixelV4 which will be done fully in GOLANG.

# Thanks to...
- [iTEM](https://tem.cx/) for supplying much of the data used for the item database module of Skypixel and its owner [TGWaffles](https://github.com/TGWaffles/) for creating it
- [artificialair](https://github.com/artificialair/) for helping me a LOT in the __EARLY__ days of Skypixel when I was just getting back into development and was very bad at it
- [Antisniper](https://api.antisniper.net/) for supplying the initial rank tracker data
- [matdev](https://matdoes.dev/) for supplying a [VERY large Minecraft player database](https://matdoes.dev/minecraft-uuids) used in the bots backend
- [Hypixel](https://api.hypixel.net/) for making this project possible
