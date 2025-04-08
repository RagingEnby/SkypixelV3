import json
import asyncio

from cogs import wikitracker


async def main():
    data = await wikitracker.get_edits()


if __name__ == "__main__":
    asyncio.run(main())
    