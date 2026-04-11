"""Rate limiter to cap applications per run and enforce cooldown."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforces a maximum number of applications per run."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._max = config.get("safety", {}).get("max_applications_per_run", 10)
        self._count = 0

    def can_proceed(self) -> bool:
        if self._count >= self._max:
            logger.warning("Rate limit reached (%d/%d)", self._count, self._max)
            return False
        return True

    def record(self) -> None:
        self._count += 1
        logger.debug("Applications this run: %d/%d", self._count, self._max)

    @property
    def remaining(self) -> int:
        return max(0, self._max - self._count)
