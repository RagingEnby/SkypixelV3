import asyncio
import logging
from typing import Optional

import aiohttp

import constants

logger = logging.getLogger(__name__)

SESSION: Optional[aiohttp.ClientSession] = None
CLOSED: bool = False


async def close():
    global CLOSED, SESSION
    CLOSED = True
    # use a try except loop instead of `if SESSION and not
    # SESSION.closed` because sometimes .closed on aiohttp.ClientSession bugs out
    try:
        await SESSION.close()  # type: ignore
        logger.info("Closed aiohttp session")
    except Exception as e:
        logger.warning(f"unable to close asyncreqs session {e} (this is 99% prob ok)")


async def get(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    if CLOSED:
        logger.error("asyncreqs.get() called after shutdown")
        raise RuntimeError('asyncreqs.get() called after shutdown')

    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        logger.warning('<!> asyncreqs.get() had to create a session')

    try:
        async with SESSION.get(*args, **kwargs) as response:
            logger.info(f"GET {response.url} {response.status}")
            try:
                await response.json()
            except:  # type: ignore
                await response.read()
            return response
    except aiohttp.ClientHttpProxyError as e:
        logger.error(f"Proxy error: {e} retrying in 2s...")
        await asyncio.sleep(2)
        return await get(*args, **kwargs)


async def proxy_get(*args, **kwargs) -> aiohttp.ClientResponse:
    return await get(
        *args,
        proxy=constants.PROXY,
        proxy_auth=constants.PROXY_AUTH,
        **kwargs
    )


async def post(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    if CLOSED:
        logger.error("asyncreqs.post() called after shutdown")
        raise RuntimeError('asyncreqs.post() called after shutdown')

    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        logger.warning('<!> asyncreqs.post() had to create a session')

    async with SESSION.post(*args, **kwargs) as response:
        logger.info(f"POST {response.url} {response.status}")
        try:
            await response.json()
            logger.debug("successfully got json")
        except:  # type: ignore
            await response.read()
            logger.debug("successfully read response")
        return response
