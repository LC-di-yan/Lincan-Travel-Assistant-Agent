"""Own reusable provider clients in the Web/CLI event-loop lifecycle."""

import asyncio
import logging
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

import httpx

_clients = WeakKeyDictionary()


def shared_client(service: str, **kwargs):
    try:
        clients = _clients.get(asyncio.get_running_loop())
    except RuntimeError:
        return None
    if clients is None:
        return None
    if service not in clients:
        clients[service] = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=24, max_keepalive_connections=8, keepalive_expiry=30),
            **kwargs,
        )
    return clients[service]


@asynccontextmanager
async def provider_client(service: str, **kwargs):
    client = shared_client(service, **kwargs)
    if client is not None:
        yield client
    else:
        # Standalone skills and ASGI test transports may not run the lifespan.
        async with httpx.AsyncClient(**kwargs) as client:
            yield client


@asynccontextmanager
async def provider_resources():
    # HTTPX INFO includes entire request URLs, including Amap keys and translated text.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    loop = asyncio.get_running_loop()
    if loop in _clients:
        yield
        return
    clients = {}
    _clients[loop] = clients
    try:
        yield
    finally:
        del _clients[loop]
        await asyncio.gather(*(client.aclose() for client in clients.values()))


async def amap_json(url: str, params: dict):
    try:
        async with asyncio.timeout(9), provider_client("amap", timeout=httpx.Timeout(7, connect=3, pool=2)) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except (TimeoutError, httpx.HTTPError, ValueError):
        # Don't let the request URL (including the key) escape with the error.
        raise ValueError("高德地图请求失败或返回无法读取的数据") from None
    if not isinstance(data, dict):
        raise ValueError("高德地图返回无法读取的数据")
    return data
