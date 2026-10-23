"""The per-torrent lock and cancel flags shared by the verifier and the cancel path.

A Cancel tapped while a check is running must always win (RESEARCH Pitfall 10). The verifier hands
a torrent off while holding that torrent's lock, and re-reads the cancel flag inside it; the cancel
path (plan 02.1-08) raises the flag first and deletes while holding the same lock. So either the
hand-off finished before the delete started, or it sees the flag and links nothing.

Keys are lower-cased info-hashes. State lives in memory: a restart clears the flags, which is safe
because a hash qBittorrent no longer lists is never a candidate and every other torrent is simply
checked again.
"""

import asyncio


class HandoffGuard:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._cancels: set[str] = set()

    def lock(self, torrent_hash: str) -> asyncio.Lock:
        """The one lock of a torrent; the same object for every caller."""
        return self._locks.setdefault(torrent_hash.lower(), asyncio.Lock())

    def request_cancel(self, torrent_hash: str) -> None:
        self._cancels.add(torrent_hash.lower())

    def clear_cancel(self, torrent_hash: str) -> None:
        """Lower a flag whose cancel is over, keeping the lock (a waiter may hold it).

        Without this a torrent added again under the same info-hash right after a Cancel would
        inherit the flag until the verifier's next tick, or for good if it listed the new torrent.
        """
        self._cancels.discard(torrent_hash.lower())

    def cancel_requested(self, torrent_hash: str) -> bool:
        return torrent_hash.lower() in self._cancels

    def forget(self, torrent_hash: str) -> None:
        """Drop the flag and the lock of a torrent that is gone (a held lock stays until freed)."""
        key = torrent_hash.lower()
        self._cancels.discard(key)
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            del self._locks[key]

    def known(self) -> set[str]:
        """Every hash that has a flag or a lock, so a tick can forget the ones that are gone."""
        return set(self._cancels) | set(self._locks)
