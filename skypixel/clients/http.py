import asyncio
import logging
from typing import Any, Literal
from urllib.parse import urlsplit

import curl_cffi
from curl_cffi.const import CurlHttpVersion
from curl_cffi.requests.exceptions import RequestException

from skypixel.settings import load_api_url

logger = logging.getLogger(__name__)
SESSION: curl_cffi.AsyncSession | None = None
CLOSED = False
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 30
# The bot runs on the same host as api.ragingenby.dev. Calling it directly
# skips Cloudflare, so its limits and bot checks never apply to the bot.
API_URL: str = load_api_url()
# The API rejects requests past 200 in flight across all clients.
API_CONCURRENCY: int = 16
_api_slots: asyncio.Semaphore = asyncio.Semaphore(API_CONCURRENCY)


def is_api_url(url: str) -> bool:
    return url.startswith(API_URL + "/")


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"


async def close() -> None:
    global CLOSED, SESSION
    if CLOSED:
        return
    CLOSED = True
    session, SESSION = SESSION, None
    if session is not None:
        await session.close()


async def get_session() -> curl_cffi.AsyncSession:
    global SESSION
    if CLOSED:
        raise RuntimeError("The HTTP client has shut down.")
    if SESSION is None:
        # Cloudflare resets multiplexed HTTP/2 streams on curl_cffi's default
        # session, causing curl (55)/(56) errors on concurrent Hypixel polls.
        SESSION = curl_cffi.AsyncSession(
            discard_cookies=True,
            timeout=(10, 30),
            http_version=CurlHttpVersion.V1_1,
        )
    return SESSION


async def request(
    method: Literal["GET", "POST"], *args, **kwargs
) -> curl_cffi.Response:
    attempts = kwargs.pop("attempts", 3 if method == "GET" else 1)
    retry_statuses = kwargs.pop("retry_statuses", RETRY_STATUSES)
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError("The request attempt count must be a positive integer.")
    session = await get_session()
    url: Any = args[0] if args else kwargs.get("url", "")
    api: bool = isinstance(url, str) and is_api_url(url)
    for attempt in range(attempts):
        delay = min(2**attempt, 5)
        try:
            if api:
                async with _api_slots:
                    response = await session.request(method, *args, **kwargs)
            else:
                response = await session.request(method, *args, **kwargs)
        except RequestException:
            if attempt == attempts - 1:
                raise
            logger.warning("HTTP %s failed. Retrying attempt %s.", method, attempt + 2)
        else:
            logger.info(
                "%s %s %s", method, safe_url(response.url), response.status_code
            )
            if (
                method != "GET"
                or response.status_code not in retry_statuses
                or attempt == attempts - 1
            ):
                return response
            retry_after = response.headers.get("Retry-After")
            if isinstance(retry_after, str) and retry_after.isdigit():
                delay = max(delay, min(int(retry_after), MAX_RETRY_AFTER))
        await asyncio.sleep(delay)
    raise RuntimeError("The HTTP request did not complete.")


async def get(*args, **kwargs) -> curl_cffi.Response:
    return await request("GET", *args, **kwargs)


async def post(*args, **kwargs) -> curl_cffi.Response:
    return await request("POST", *args, **kwargs)


async def get_json(url: str, **kwargs) -> Any:
    response = await get(url, **kwargs)
    response.raise_for_status()
    return response.json()
