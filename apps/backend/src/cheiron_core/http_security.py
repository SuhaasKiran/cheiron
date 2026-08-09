"""Small, bounded HTTP protections for the public chart endpoint."""

from __future__ import annotations

import hmac
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The result of one rate-limit check."""

    allowed: bool
    retry_after_seconds: int = 0


class ClientRequestRateLimiter:
    """Bound request history per client without external persistence.

    This limiter intentionally protects one process. Railway deployments with multiple
    replicas need a shared edge or data-store limiter for a global quota.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("max_requests must be a positive integer.")
        if type(window_seconds) is not int or window_seconds < 1:
            raise ValueError("window_seconds must be a positive integer.")
        if type(max_clients) is not int or max_clients < 1:
            raise ValueError("max_clients must be a positive integer.")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._requests_by_client: OrderedDict[str, deque[float]] = OrderedDict()

    @property
    def tracked_client_count(self) -> int:
        """Return the number of client histories retained in bounded memory."""

        return len(self._requests_by_client)

    def check(self, client_id: str) -> RateLimitDecision:
        """Record an allowed request or return its bounded retry delay."""

        if not isinstance(client_id, str) or not client_id:
            raise ValueError("client_id must be a non-empty string.")
        now = self._clock()
        history = self._requests_by_client.pop(client_id, deque())
        cutoff = now - self._window_seconds
        while history and history[0] <= cutoff:
            history.popleft()

        if len(history) >= self._max_requests:
            self._requests_by_client[client_id] = history
            retry_after = max(1, math.ceil(history[0] + self._window_seconds - now))
            return RateLimitDecision(False, retry_after)

        history.append(now)
        self._requests_by_client[client_id] = history
        while len(self._requests_by_client) > self._max_clients:
            self._requests_by_client.popitem(last=False)
        return RateLimitDecision(True)


class ApiKeyAuthenticator:
    """Check an optional allowlist without exposing configured key values."""

    def __init__(self, api_keys: Iterable[str]) -> None:
        self._api_keys = tuple(api_keys)

    @property
    def enabled(self) -> bool:
        """Return whether requests require an API key."""

        return bool(self._api_keys)

    def is_authorized(self, presented_key: str | None) -> bool:
        """Return true for an allowlisted key using constant-time comparisons."""

        if not self.enabled:
            return True
        if not isinstance(presented_key, str):
            return False
        return any(hmac.compare_digest(presented_key, key) for key in self._api_keys)
