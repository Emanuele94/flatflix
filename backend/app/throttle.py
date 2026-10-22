"""One sliding-window limiter for the login, search and download routes (D-18, SEC-05, D-38)."""

import time
from collections import deque
from collections.abc import Callable

# Window of the search and download start limits (D-38); the login limiter sets its own.
THROTTLE_WINDOW_SECONDS = 60


class SlidingWindowThrottle:
    """Sliding-window limit: per address, plus an optional ceiling for all addresses.

    Used three times: the login attempts (D-18, WR-07, with the ceiling), and the search and
    download starts (SEC-05, D-38, per address only).

    `try_acquire` checks and records in one synchronous step with no `await`
    in between, so concurrent requests cannot all slip past the limit: a slot is
    reserved BEFORE the slow argon2 check runs. State is in memory; a restart
    clears it, which is acceptable for a one-account household LAN portal.

    Two limits apply (WR-07):

    - per address, `max_attempts` per window. When every client shows up as the same address
      (a NAT or a proxy that hides the real one), that address is the whole household, and one
      person typing the wrong password `max_attempts` times blocks everybody until the window
      ends. A correct login clears the counter of its address.
    - across all addresses, `global_max_attempts` per window, so guesses spread over many
      addresses (or a proxy header that cannot be trusted) stay bounded. Only attempts that are
      allowed are recorded, so the state never holds more than this many entries.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
        global_max_attempts: int | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.global_max_attempts = global_max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._all: deque[tuple[float, str]] = deque()

    def try_acquire(self, ip: str) -> float | None:
        """None: allowed and the slot is recorded. A float: seconds until a slot frees up."""
        now = self._clock()
        cutoff = now - self.window_seconds
        while self._all and self._all[0][0] <= cutoff:
            self._all.popleft()
        attempts = self._attempts.get(ip)
        if attempts is not None:
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del self._attempts[ip]
                attempts = None
        waits = []
        if attempts is not None and len(attempts) >= self.max_attempts:
            waits.append(attempts[0] + self.window_seconds - now)
        if self.global_max_attempts is not None and len(self._all) >= self.global_max_attempts:
            waits.append(self._all[0][0] + self.window_seconds - now)
        if waits:
            return max(waits)
        if attempts is None:
            attempts = self._attempts[ip] = deque()
        attempts.append(now)
        self._all.append((now, ip))
        return None

    def reset(self, ip: str) -> None:
        """Forget the recorded slots of that address (a correct login)."""
        self._attempts.pop(ip, None)
        self._all = deque(entry for entry in self._all if entry[1] != ip)
