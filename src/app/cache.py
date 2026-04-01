"""TTL-based in-memory cache for expensive external API calls (Gemini search)."""
import threading
import time
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with per-entry TTL expiration."""

    def __init__(self, ttl: int = 300) -> None:
        self.default_ttl = ttl
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Return cached value or None if missing / expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with an optional per-entry TTL (falls back to default)."""
        ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> bool:
        """Remove a single entry; return True if it existed."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> int:
        """Remove all entries; return count of removed items."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def size(self) -> int:
        """Return total number of entries (including expired-but-not-yet-evicted)."""
        return len(self._store)

    def evict_expired(self) -> int:
        """Proactively remove expired entries; return count evicted."""
        now = time.monotonic()
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)

    def stats(self) -> dict[str, int]:
        """Return cache statistics (includes eviction pass)."""
        evicted = self.evict_expired()
        return {
            "size": self.size(),
            "ttl_seconds": self.default_ttl,
            "evicted_now": evicted,
        }


# ---------------------------------------------------------------------------
# Singleton instances — imported by routers
# ---------------------------------------------------------------------------

#: 5-minute cache for search results (places, hotels, flights).
search_cache = TTLCache(ttl=300)
