import time
from collections import defaultdict, deque


class Limiter:
    """Per-key sliding hour window plus a global daily call budget (protects the API bill)."""

    def __init__(self, per_hour: int, daily: int, clock=time.time):
        self.per_hour, self.daily, self.clock = per_hour, daily, clock
        self.hits: dict[str, deque] = defaultdict(deque)
        self.day_start, self.day_count = clock(), 0

    def allow(self, key: str, cost: int = 1) -> bool:
        now = self.clock()
        if now - self.day_start > 86400:
            self.day_start, self.day_count = now, 0
        q = self.hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) + cost > self.per_hour or self.day_count + cost > self.daily:
            return False
        q.extend([now] * cost)
        self.day_count += cost
        return True
