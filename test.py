import json
import asyncio

from cogs import alphatracker


async def main():
    data = await alphatracker.get_alpha_data()
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
    