import asyncio
import logging

from dns.exception import DNSException
from mcstatus import JavaServer
from mcstatus.responses import JavaStatusResponse

logger = logging.getLogger(__name__)
LOOKUP_TIMEOUT: int = 10
STATUS_ATTEMPTS: int = 3


async def get_status(
    host: str, *, attempts: int = STATUS_ATTEMPTS
) -> JavaStatusResponse:
    """Ping a Minecraft server, retrying DNS and connection errors.

    Raises the last error once every attempt has failed.
    """
    if attempts < 1:
        raise ValueError("The status attempt count must be a positive integer.")
    attempt: int = 0
    while True:
        try:
            server: JavaServer = await JavaServer.async_lookup(
                host, timeout=LOOKUP_TIMEOUT
            )
            return await server.async_status()
        except (OSError, DNSException):
            attempt += 1
            if attempt == attempts:
                raise
            logger.warning(
                "The status lookup for %s failed. Retrying attempt %s.",
                host,
                attempt + 1,
            )
            await asyncio.sleep(min(2 ** (attempt - 1), 5))
