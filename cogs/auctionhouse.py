import asyncio
import logging
import time
import traceback
from typing import Any, Coroutine

import disnake
from disnake.ext import commands

import constants
from cogs import ranktracker
from modules import asyncreqs, mojang
from modules import colors
from modules import parser
from modules import utils

logger = logging.getLogger(__name__)
ACTIVE_URL: str = "https://api.hypixel.net/v2/skyblock/auctions?page=0"


async def get_active_auctions() -> dict[str, Any]:
    try:
        response = await asyncreqs.get(ACTIVE_URL)
        response.raise_for_status()
        return await response.json()
    except Exception as e:
        logger.error(f'error getting /skyblock/auctions: {e}')
        await asyncio.sleep(5)
        return await get_active_auctions()
    

async def make_auction_embed(auction: dict[str, Any], item: dict[str, Any]) -> disnake.Embed:
    tag = item.get('tag', {})
    display = tag.get('display', {})
    embed = disnake.Embed(
        url=constants.AUCTION_URL.format(auction['uuid']),
        title=auction['item_name'],
        color=display.get('color') or constants.RARITY_COLORS.get(auction.get('tier', 'COMMON'))
    )
    embed.set_thumbnail(utils.get_item_image(
        item_id=tag.get('ExtraAttributes', {}).get('id', 'DIRT'),
        color=f"{display['color']:06X}"[:6] if display.get('color') else None,
        durability=tag.get('Damage')
    ))
    embed.set_footer(text="/viewauction " + auction['uuid'])
    embed.add_field(
        name="Price" if auction['bin'] else "Starting Bid",
        value=utils.numerize(auction['starting_bid']),
        inline=True
    )
    if not auction['bin']:
        embed.add_field(
            name="Auction End",
            value=f"<t:{auction['end'] // 1000}:R>",
            inline=True
        )
    auctioneer = await mojang.get(auction['auctioneer'])
    embed.set_author(
        name=auctioneer.name,
        icon_url=auctioneer.avatar,
        url=constants.STATS_URL.format(auctioneer.id)
    )
    return embed


class AHListener:
    @staticmethod
    async def on_admin_spawned_auction(auction: dict[str, Any], item: dict[str, Any]):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Origin Tag",
            value=item['tag']['ExtraAttributes']['originTag'],
            inline=True
        )
        await utils.send_to_channel(constants.ADMIN_SPAWNED_ITEMS_CHANNEL, embed=embed)

    @staticmethod
    async def on_og_reforge_auction(auction: dict[str, Any], item: dict[str, Any]):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Reforge",
            value=item['tag']['ExtraAttributes']['modifier'],
            inline=True
        )
        await utils.send_to_channel(constants.OG_REFORGES_CHANNEL, embed=embed)

    @staticmethod
    async def on_semi_og_reforge_auction(auction: dict[str, Any], item: dict[str, Any]):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Reforge",
            value=item['tag']['ExtraAttributes']['modifier'],
            inline=True
        )
        await utils.send_to_channel(constants.SEMI_OG_REFORGES_CHANNEL, embed=embed)

    @staticmethod
    async def on_poi_auction(auction: dict[str, Any], item: dict[str, Any]):
        rankname = utils.remove_color_codes(await ranktracker.get_rankname(auction['auctioneer']))
        embed = await make_auction_embed(auction, item)
        embed.set_author(
            name=rankname,
            icon_url=constants.MC_HEAD_IMAGE.format(auction['auctioneer'])
        )
        await utils.send_to_channel(constants.POI_AUCTIONS_CHANNEL, embed=embed)

    @staticmethod
    async def on_old_item_auction(auction: dict[str, Any], item: dict[str, Any], timestamp: int):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Created At",
            value=f"<t:{timestamp}>\n-# <t:{timestamp}:R>",
            inline=True
        )
        await utils.send_to_channel(constants.OLD_ITEM_AUCTIONS_CHANNEL, embed=embed)

    @staticmethod
    async def on_seymour_auction(auction: dict[str, Any], item: dict[str, Any], hex_code: str):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Hex Code",
            value=f"#{hex_code}",
            inline=True
        )
        armor_type = constants.SEYMOUR_IDS[item['tag']['ExtraAttributes']['id']]
        top_5 = colors.get_top_5(armor_type, hex_code)
        embed.description = '```\n' + '\n'.join([f"{k}: {round(v, 2)}" for k, v in top_5.items()]) + '```'
        await utils.send_to_channel(constants.SEYMOUR_AUCTIONS_CHANNEL, embed=embed)

    @staticmethod
    async def on_exotic_auction(auction: dict[str, Any], item: dict[str, Any], exotic_type: colors.ExoticType, hex_code: str):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Hex Code",
            value=f"#{hex_code}"
        )
        embed.add_field(
            name="Exotic Type",
            value=exotic_type.replace('_', ' ').title(),
            inline=True
        )
        send_tasks = [utils.send_to_channel(
            constants.EXOTIC_AUCTIONS_CHANNEL,
            embed=embed
        )]
        thread_id = constants.EXOTIC_AUCTIONS_THREADS.get(exotic_type)
        if thread_id:
            send_tasks.append(utils.send_to_channel(
                constants.EXOTIC_AUCTIONS_THREADS_PARENT,
                thread_id=thread_id,
                embed=embed
            ))
        await asyncio.gather(*send_tasks)

    @staticmethod
    async def on_cake_soul_auction(auction: dict[str, Any], item: dict[str, Any]):
        embed = await make_auction_embed(auction, item)
        dye_data = constants.MINECRAFT_DYES.get(item.get('tag', {}).get('Damage'))
        if dye_data:
            embed.title = dye_data['colorName'].title() + " Cake Soul"  # type: ignore[index]
        await utils.send_to_channel(constants.CAKE_SOUL_AUCTIONS_CHANNEL, embed=embed)
        


class AuctionTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None

    @staticmethod
    async def on_auction(auction: dict[str, Any]):
        item = parser.decode_single(auction['item_bytes'])
        extra_attributes = item.get('tag', {}).get('ExtraAttributes', {})
        if not extra_attributes.get('uuid'):
            return
        item_id = extra_attributes.get('id')
        timestamp = utils.normalize_timestamp(extra_attributes['timestamp']) if extra_attributes.get('timestamp') else None
        color = item.get('tag', {}).get('display', {}).get('color')
        hex_code = f"{color:06X}"[:6] if color else None
        exotic_type = colors.get_exotic_type(item_id, hex_code)\
                      if item_id and hex_code and not extra_attributes.get('dye_item') else None
        tasks: list[Coroutine] = []

        if extra_attributes.get('originTag') in constants.ADMIN_ORIGIN_TAGS:
            tasks.append(AHListener.on_admin_spawned_auction(auction, item))
        if extra_attributes.get('modifier') in constants.OG_REFORGES:
            tasks.append(AHListener.on_og_reforge_auction(auction, item))
        if 'accessories' in auction.get('categories', []) and extra_attributes.get('modifier', 'none') != 'none':
            tasks.append(AHListener.on_semi_og_reforge_auction(auction, item))
        if auction['auctioneer'] in ranktracker.POI_UUIDS:
            tasks.append(AHListener.on_poi_auction(auction, item))
        if timestamp and timestamp <= 1575910800 and auction['starting_bid'] <= 100_000_000:
            tasks.append(AHListener.on_old_item_auction(auction, item, timestamp))
        if item_id in constants.SEYMOUR_IDS:
            tasks.append(AHListener.on_seymour_auction(auction, item, hex_code))
        if exotic_type:
            tasks.append(AHListener.on_exotic_auction(auction, item, exotic_type, hex_code))
        if item_id == "CAKE_SOUL":
            tasks.append(AHListener.on_cake_soul_auction(auction, item))
        if tasks:
            await asyncio.gather(*tasks)

    async def main(self):
        last_last_updated = 0
        while True:
            try:
                page_0 = await get_active_auctions()
                if page_0['lastUpdated'] != last_last_updated:
                    new_auctions = [
                        a for a in page_0['auctions']
                        if a.get('start', 0) >= last_last_updated
                    ]
                    logger.debug(f"got {len(new_auctions)} new auctions")
                    await asyncio.gather(*[self.on_auction(a) for a in new_auctions])
                    logger.debug('processed auctions')
                    last_last_updated = page_0['lastUpdated']
                next_update = last_last_updated // 1000 + 60
                time_until_update = next_update - time.time()
                if time_until_update <= 0:
                    time_until_update = 1
                await asyncio.sleep(time_until_update)
            except Exception:
                logger.error(traceback.format_exc())
                await asyncio.sleep(15)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
