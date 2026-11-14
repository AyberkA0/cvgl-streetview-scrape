"""HTTP helpers shared by the collection stages."""

import asyncio
from collections import Counter

import aiohttp
from tqdm import tqdm


class NotFound(Exception):
    """The requested resource does not exist on the server."""


class FetchError(Exception):
    """The request kept failing after all retries."""


async def fetch(session, url, *, method="GET", absent=(), retries=4, **kwargs):
    """Returns the response body, or None for a status listed in `absent`.

    Raises NotFound on HTTP 404 and FetchError once the retries are used up.
    """
    reason = None
    for attempt in range(retries):
        if attempt:
            await asyncio.sleep(2 ** (attempt - 1))
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status in absent:
                    return None
                if response.status == 404:
                    raise NotFound(url)
                if response.status == 200:
                    return await response.read()
                reason = f"HTTP {response.status}"
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            reason = repr(error)
    raise FetchError(f"{reason} for {url}")


async def run_all(items, worker, *, concurrency, label, unit):
    """Runs `worker(session, item)` over all items with a progress bar.

    Returns a Counter of outcomes ("ok", "unavailable", "failed") and the
    list of error messages of the failed items.
    """
    outcomes, errors = Counter(), []
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency * 4)
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        with tqdm(total=len(items), desc=label, unit=unit) as bar:

            async def one(item):
                async with semaphore:
                    try:
                        await worker(session, item)
                        outcome = "ok"
                    except NotFound:
                        outcome = "unavailable"
                    except Exception as error:
                        outcome = "failed"
                        errors.append(f"{item}: {error}")
                outcomes[outcome] += 1
                bar.update()

            await asyncio.gather(*(one(item) for item in items))

    return outcomes, errors
