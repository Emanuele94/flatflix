"""Small network helpers shared by the proxy middleware and the download pipeline."""

import asyncio
import socket


async def resolve_host(host: str) -> list[str]:
    """Every IP address a host name resolves to (a literal address resolves to itself)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]
