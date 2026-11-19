import math
import time
from collections import OrderedDict, deque

from app.auth.security import token_hash
from app.core.errors import AppError
from app.domain.constants import ErrorCode


class AuthRateLimiter:
    """Bounded single-process rolling windows; never retains raw email/IP."""

    def __init__(self, email_limit=10, address_limit=60, window_seconds=600, clock=time.monotonic):
        self.email_limit = email_limit
        self.address_limit = address_limit
        self.window = window_seconds
        self.clock = clock
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, address: str, email: str | None = None):
        now = self.clock()
        for key in list(self._buckets):
            queue = self._buckets[key]
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if not queue:
                del self._buckets[key]
        keys = [("address:" + token_hash(address), self.address_limit)]
        if email is not None:
            keys.append(("email:" + token_hash(email), self.email_limit))
        for key, limit in keys:
            queue = self._buckets.get(key)
            if queue and len(queue) >= limit:
                retry = max(1, math.ceil(queue[0] + self.window - now))
                raise AppError(
                    ErrorCode.RATE_LIMITED,
                    "시도가 많아요. 잠시 후 다시 시도해 주세요.",
                    429,
                    {"retryAfterSeconds": retry},
                )
        # Keep the address bucket when new emails are supplied. Stop accepting new
        # distinct buckets at capacity instead of evicting a still-active limit.
        new_keys = sum(key not in self._buckets for key, _ in keys)
        if len(self._buckets) + new_keys > 4096:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "잠시 후 다시 시도해 주세요.",
                429,
                {"retryAfterSeconds": 60},
            )
        for key, _ in keys:
            self._buckets.setdefault(key, deque()).append(now)
