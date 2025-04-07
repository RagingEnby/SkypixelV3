import asyncio

from cogs import motdtracker

async def main():
    await motdtracker.get_motd("hypixel.net")

if __name__ == "__main__":
    asyncio.run(main())