"""STUB for the RED commit: wrong-valued on purpose, replaced in the GREEN commit."""

import asyncio


class HandoffGuard:
    def lock(self, torrent_hash: str) -> asyncio.Lock:
        return asyncio.Lock()

    def request_cancel(self, torrent_hash: str) -> None:
        return None

    def cancel_requested(self, torrent_hash: str) -> bool:
        return False

    def forget(self, torrent_hash: str) -> None:
        return None

    def known(self) -> set[str]:
        return set()
