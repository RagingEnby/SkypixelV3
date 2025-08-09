import asyncio
import logging
import time
import traceback
from typing import Any, Coroutine
from pymongo import UpdateOne

import disnake
from disnake.ext import commands

import constants
from cogs import ranktracker
from modules import asyncreqs, mojang
from modules import colors
from modules import parser
from modules import utils
from modules import mongodb
from modules import datamanager

logger = logging.getLogger(__name__)
ACTIVE_URL: str = "https://api.hypixel.net/v2/skyblock/auctions?page=0"
ENDED_URL: str = "https://api.hypixel.net/v2/skyblock/auctions_ended"

# keep track of processed auctions, this is normally VERY
# bad practice but I need it to debug an error. It will be
# removed afterwards.
processed_auctions = datamanager.LimitedSet(limit=50_000)


# no attempt limit on this because im a shit dev
# (it would require extra error handling elsewhere)
# and i dont forsee it being an issue
async def get_active_auctions() -> dict[str, Any]:
    while True:
        try:
            response = await asyncreqs.get(ACTIVE_URL)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f'error getting /skyblock/auctions: {e}')
            await asyncio.sleep(5)
    

async def get_ended_auctions() -> dict[str, Any]:
    while True:
        try:
            response = await asyncreqs.get(ENDED_URL)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f'error getting /skyblock/auctions_ended: {e}')
            await asyncio.sleep(5)
        

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
        durability=item.get('Damage')
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
        dye_data = constants.MINECRAFT_DYES.get(item.get('Damage'))  # type: ignore
        if dye_data:
            embed.title = dye_data['colorName'].title() + " Cake Soul"  # type: ignore[index]
            embed.color = dye_data['hex']  # type: ignore
        cake_owner = item.get('tag', {}).get('ExtraAttributes', {}).get('cake_owner') or "None"
        embed.add_field(
            name="Cake Owner",
            value=utils.remove_color_codes(cake_owner),
            inline=True
        )
        pings = []
        if auction['bin'] and auction['starting_bid'] <= 7_500_000 and dye_data and dye_data['colorName'] == "red":
            pings.append(f"<@&{constants.CHEAP_RED_SOUL_ROLE}>")
        if auction['bin'] and auction['starting_bid'] <= 5_000_000:
            pings.append(f"<@&{constants.CHEAP_SOUL_ROLE}>")
        await utils.send_to_channel(constants.CAKE_SOUL_AUCTIONS_CHANNEL, ' '.join(pings), embed=embed)

    @staticmethod
    async def on_editioned_auction(auction: dict[str, Any], item: dict[str, Any], edition: int, timestamp: int | None):
        embed = await make_auction_embed(auction, item)
        embed.add_field(
            name="Edition",
            value=f"#{utils.commaize(edition)}",
            inline=True
        )
        recipient_name = item.get('tag', {}).get('ExtraAttributes', {}).get('recipient_name')
        if recipient_name:
            embed.add_field(
                name="Recipient Name",
                value=utils.esc_mrkdwn(utils.remove_color_codes(recipient_name)),
                inline=True
            )
        if timestamp:
            embed.add_field(
                name="Created At",
                value=f"<t:{timestamp}>\n-# <t:{timestamp}:R>",
                inline=True
            )
        await utils.send_to_channel(constants.EDITIONED_AUCTIONS_CHANNEL, embed=embed)


class AuctionTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.active_db: mongodb.Collection | None = None
        self.ended_db: mongodb.Collection | None = None
        self.active_db_queue = []
        self.ended_db_queue = []
        self.last_scanned_active = 0
        self.last_scanned_ended = 0

    async def upload_queue(self):
        if self.active_db_queue:
            if not self.active_db:
                self.active_db = mongodb.Collection('SkyBlock', 'auctions')
            await self.active_db.update_many(self.active_db_queue)
            self.active_db_queue.clear()
            logger.debug('logged auctions to mongo')
        if self.ended_db_queue:
            if not self.ended_db:
                self.ended_db = mongodb.Collection('SkyBlock', 'ended_auctions')
            await self.ended_db.update_many(self.ended_db_queue)
            self.ended_db_queue.clear()
            logger.debug('logged ended auctions to mongo')

    
    def log_auction(self, auction: dict[str, Any], item: dict[str, Any], ended: bool):
        doc = auction.copy()
        doc['item_data'] = item
        if ended:
            doc['_id'] = doc.pop('auction_id')
            self.ended_db_queue.append(doc)
        else:
            doc['_id'] = doc.pop('uuid')
            self.active_db_queue.append(doc)
    
    async def on_auction(self, auction: dict[str, Any], new: bool = True):
        try:
            item = parser.decode_single(auction['item_bytes'])
        except UnicodeDecodeError as e:
            logger.error(f"UNICODE DECODE ERROR: {e} {auction['uuid']} --- {auction['item_bytes']}")
            return
        self.log_auction(auction, item, ended=False)
        if not new:
            return
        if auction['uuid'] in processed_auctions:
            logger.error('\n'.join([
                " -- AUCTION DOUBLE PROCESSED -- ",
                f"UUID: {auction['uuid']}",
                f"Last Updated: {auction['last_updated']}",
                f"Start: {auction['start']}",
                f"Last Scan: {self.last_scanned_active}"
            ]))
            return
        processed_auctions.add(auction['uuid'])
        extra_attributes = item.get('tag', {}).get('ExtraAttributes', {})
        if not extra_attributes.get('uuid'):
            return
        item_id = extra_attributes.get('id')
        timestamp = utils.normalize_timestamp(extra_attributes['timestamp']) if extra_attributes.get('timestamp') else None
        color = item.get('tag', {}).get('display', {}).get('color')
        hex_code = f"{color:06X}"[:6] if color else None
        exotic_type = colors.get_exotic_type(item_id, hex_code)\
                      if item_id and hex_code and not extra_attributes.get('dye_item') else None
        edition = extra_attributes.get('edition', extra_attributes.get('basket_edition'))
        accessory = 'accessories' in auction.get('categories', [])
        tasks: list[Coroutine] = []

        if extra_attributes.get('originTag') in constants.ADMIN_ORIGIN_TAGS:
            tasks.append(AHListener.on_admin_spawned_auction(auction, item))
        if not accessory and extra_attributes.get('modifier') in constants.OG_REFORGES:
            tasks.append(AHListener.on_og_reforge_auction(auction, item))
        if accessory and extra_attributes.get('modifier', 'none') != 'none':
            tasks.append(AHListener.on_semi_og_reforge_auction(auction, item))
        if auction['auctioneer'] in ranktracker.POI_UUIDS:
            tasks.append(AHListener.on_poi_auction(auction, item))
        if timestamp and timestamp <= 1575910800 and auction['starting_bid'] <= 100_000_000:
            tasks.append(AHListener.on_old_item_auction(auction, item, timestamp))
        if item_id in constants.SEYMOUR_IDS and hex_code:
            tasks.append(AHListener.on_seymour_auction(auction, item, hex_code))
        if exotic_type and hex_code:
            tasks.append(AHListener.on_exotic_auction(auction, item, exotic_type, hex_code))  # type: ignore[assignment]
        if item_id == "CAKE_SOUL":
            tasks.append(AHListener.on_cake_soul_auction(auction, item))
        # for some reason there are mementos with edition -1 (missing)
        if edition and edition > 0:
            tasks.append(AHListener.on_editioned_auction(auction, item, edition, timestamp))
        if tasks:
            await asyncio.gather(*tasks)

    async def on_auction_end(self, auction: dict[str, Any]):
        try:
            item = parser.decode_single(auction['item_bytes'])
        except UnicodeDecodeError as e:
            logger.error(f"UNICODE DECODE ERROR: {e} {auction['auction_id']} --- {auction['item_bytes']}")
            return
        self.log_auction(auction, item, ended=True)

    async def active_scanner(self) -> float:
        page_0 = await get_active_auctions()
        if not self.last_scanned_active:
            self.last_scanned_active = page_0['lastUpdated']
        if page_0['lastUpdated'] != self.last_scanned_active:
            # i used to filter out non-uuied auctions
            # here, but for some reason auction.item_uuid
            # is missing on like 5% of auctioned items
            # with uuids 😭
            auctions = [
                a for a in page_0['auctions']
                if a.get('last_updated', a.get('start', 0)) >= self.last_scanned_active
            ]
            logger.debug(f"got {len(auctions)} auctions")
            await asyncio.gather(*[self.on_auction(
                auction=a,
                new=a.get('start', 0) >= self.last_scanned_active)
            for a in auctions])
            logger.debug('processed auctions')
            self.last_scanned_active = page_0['lastUpdated']
        next_update = self.last_scanned_active // 1000 + 60
        time_until_update = next_update - time.time()
        if time_until_update < 0:
            return 1.0
        return time_until_update

    async def ended_scanner(self) -> float:
        data = await get_ended_auctions()
        if not self.last_scanned_ended:
            self.last_scanned_ended = data['lastUpdated']
        if data['lastUpdated'] != self.last_scanned_ended:
            auctions = [
                a for a in data['auctions']
                if a.get('timestamp', 0) >= self.last_scanned_ended
            ]
            logger.debug(f"got {len(auctions)} ended auctions")
            await asyncio.gather(*[
                self.on_auction_end(auction=a)
                for a in auctions
            ])
            logger.debug('processed ended auctions')
            self.last_scanned_ended = data['lastUpdated']
        next_update = self.last_scanned_ended // 1000 + 60
        time_until_update = next_update - time.time()
        if time_until_update < 0:
            return 1.0
        return time_until_update
            

    async def main(self):
        while True:
            try:
                wait_for = min(await asyncio.gather(
                    self.active_scanner(),
                    self.ended_scanner()
                ))
                asyncio.create_task(self.upload_queue())
                await asyncio.sleep(wait_for)
            except Exception:
                logger.error(traceback.format_exc())
                await asyncio.sleep(15)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
        if self.active_db:
            await self.active_db.close()
            self.active_db = None
        if self.ended_db:
            await self.ended_db.close()
            self.ended_db = None

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
