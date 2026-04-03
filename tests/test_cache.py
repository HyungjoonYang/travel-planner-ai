"""Tests for TTL cache and search endpoint caching behaviour."""
import time
import unittest.mock as mock

from fastapi.testclient import TestClient

from app.cache import TTLCache, search_cache
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# TTLCache unit tests
# ---------------------------------------------------------------------------

class TestTTLCacheBasics:
    def setup_method(self):
        self.cache = TTLCache(ttl=60)

    def test_miss_on_empty(self):
        assert self.cache.get("missing") is None

    def test_set_and_get(self):
        self.cache.set("k", "v")
        assert self.cache.get("k") == "v"

    def test_overwrite(self):
        self.cache.set("k", "v1")
        self.cache.set("k", "v2")
        assert self.cache.get("k") == "v2"

    def test_delete_existing(self):
        self.cache.set("k", "v")
        assert self.cache.delete("k") is True
        assert self.cache.get("k") is None

    def test_delete_missing_returns_false(self):
        assert self.cache.delete("nope") is False

    def test_clear_returns_count(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        assert self.cache.clear() == 2

    def test_clear_empties_store(self):
        self.cache.set("a", 1)
        self.cache.clear()
        assert self.cache.size() == 0

    def test_size(self):
        assert self.cache.size() == 0
        self.cache.set("x", 1)
        assert self.cache.size() == 1

    def test_stores_any_type(self):
        obj = {"foo": [1, 2, 3]}
        self.cache.set("complex", obj)
        assert self.cache.get("complex") == obj


class TestTTLCacheExpiration:
    def test_expired_entry_returns_none(self):
        cache = TTLCache(ttl=1)
        cache.set("k", "v")
        # Mock time to be in the future
        with mock.patch("app.cache.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 10
            assert cache.get("k") is None

    def test_per_entry_ttl_override(self):
        cache = TTLCache(ttl=3600)
        cache.set("short", "v", ttl=1)
        with mock.patch("app.cache.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 10
            assert cache.get("short") is None

    def test_not_expired_within_ttl(self):
        cache = TTLCache(ttl=300)
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_evict_expired_removes_stale_entries(self):
        cache = TTLCache(ttl=1)
        cache.set("a", 1)
        cache.set("b", 2)
        with mock.patch("app.cache.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 10
            evicted = cache.evict_expired()
        assert evicted == 2
        assert cache.size() == 0

    def test_evict_expired_keeps_live_entries(self):
        cache = TTLCache(ttl=3600)
        cache.set("live", "yes")
        with mock.patch("app.cache.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 10
            evicted = cache.evict_expired()
        assert evicted == 0
        # Live entry should still be there (monotonic baseline not mocked for get)
        assert cache.size() == 1


class TestTTLCacheStats:
    def test_stats_returns_dict(self):
        cache = TTLCache(ttl=60)
        stats = cache.stats()
        assert isinstance(stats, dict)

    def test_stats_keys(self):
        cache = TTLCache(ttl=60)
        stats = cache.stats()
        assert "size" in stats
        assert "ttl_seconds" in stats
        assert "evicted_now" in stats

    def test_stats_reflects_ttl(self):
        cache = TTLCache(ttl=99)
        assert cache.stats()["ttl_seconds"] == 99

    def test_stats_size_after_set(self):
        cache = TTLCache(ttl=60)
        cache.set("x", 1)
        assert cache.stats()["size"] == 1


# ---------------------------------------------------------------------------
# Cache admin endpoint tests
# ---------------------------------------------------------------------------

class TestCacheEndpoints:
    def setup_method(self):
        search_cache.clear()

    def test_stats_returns_200(self):
        resp = client.get("/cache/stats")
        assert resp.status_code == 200

    def test_stats_has_required_keys(self):
        resp = client.get("/cache/stats")
        data = resp.json()
        assert "size" in data
        assert "ttl_seconds" in data
        assert "evicted_now" in data

    def test_clear_returns_200(self):
        resp = client.delete("/cache")
        assert resp.status_code == 200

    def test_clear_returns_count(self):
        search_cache.set("key1", "val1")
        search_cache.set("key2", "val2")
        resp = client.delete("/cache")
        assert resp.json()["cleared"] == 2

    def test_clear_empties_cache(self):
        search_cache.set("key", "val")
        client.delete("/cache")
        assert search_cache.size() == 0

    def test_stats_size_after_clear(self):
        search_cache.set("key", "val")
        client.delete("/cache")
        resp = client.get("/cache/stats")
        assert resp.json()["size"] == 0


# ---------------------------------------------------------------------------
# Search endpoint caching integration tests
# ---------------------------------------------------------------------------

from app.web_search import DestinationSearchResult, PlaceSearchResult  # noqa: E402
from app.hotel_search import HotelResult, HotelSearchResult  # noqa: E402
from app.flight_search import FlightResult, FlightSearchResult  # noqa: E402

_PLACES_RESULT = DestinationSearchResult(
    destination="Tokyo",
    query="Tokyo",
    places=[PlaceSearchResult(name="Senso-ji", category="temple", address="Asakusa", estimated_cost=0, ai_reason="Famous temple")],
    summary="Great spots in Tokyo",
)

_HOTELS_RESULT = HotelSearchResult(
    destination="Tokyo",
    check_in="",
    check_out="",
    budget_per_night=0,
    hotels=[HotelResult(name="Park Hyatt", address="Shinjuku", price_per_night=300, rating="4.5", amenities=["pool"], ai_reason="Iconic hotel")],
    summary="Best hotels in Tokyo",
)

_FLIGHTS_RESULT = FlightSearchResult(
    departure_city="Seoul",
    arrival_city="Tokyo",
    departure_date="",
    return_date="",
    passengers=1,
    flights=[FlightResult(airline="JAL", flight_number="JL001", departure_time="09:00", arrival_time="11:00", duration="2h", price="200", stops="0", ai_reason="Direct flight")],
    summary="Flights from Seoul to Tokyo",
)


class TestSearchPlacesCache:
    def setup_method(self):
        search_cache.clear()

    def test_cache_miss_calls_service(self):
        with mock.patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.return_value = _PLACES_RESULT
            client.get("/search/places?destination=Tokyo")
            assert MockSvc.return_value.search_places.call_count == 1

    def test_cache_hit_skips_service(self):
        with mock.patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.return_value = _PLACES_RESULT
            client.get("/search/places?destination=Tokyo")
            client.get("/search/places?destination=Tokyo")
            assert MockSvc.return_value.search_places.call_count == 1

    def test_different_params_both_call_service(self):
        with mock.patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.return_value = _PLACES_RESULT
            client.get("/search/places?destination=Tokyo")
            client.get("/search/places?destination=Osaka")
            assert MockSvc.return_value.search_places.call_count == 2

    def test_case_insensitive_cache_key(self):
        with mock.patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.return_value = _PLACES_RESULT
            client.get("/search/places?destination=Tokyo")
            client.get("/search/places?destination=TOKYO")
            assert MockSvc.return_value.search_places.call_count == 1


class TestSearchHotelsCache:
    def setup_method(self):
        search_cache.clear()

    def test_cache_miss_calls_service(self):
        with mock.patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.return_value = _HOTELS_RESULT
            client.get("/search/hotels?destination=Tokyo")
            assert MockSvc.return_value.search_hotels.call_count == 1

    def test_cache_hit_skips_service(self):
        with mock.patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.return_value = _HOTELS_RESULT
            client.get("/search/hotels?destination=Tokyo")
            client.get("/search/hotels?destination=Tokyo")
            assert MockSvc.return_value.search_hotels.call_count == 1

    def test_different_check_in_dates_miss_cache(self):
        with mock.patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.return_value = _HOTELS_RESULT
            client.get("/search/hotels?destination=Tokyo&check_in=2026-05-01")
            client.get("/search/hotels?destination=Tokyo&check_in=2026-06-01")
            assert MockSvc.return_value.search_hotels.call_count == 2


class TestSearchFlightsCache:
    def setup_method(self):
        search_cache.clear()

    def test_cache_miss_calls_service(self):
        with mock.patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.return_value = _FLIGHTS_RESULT
            client.get("/search/flights?departure_city=Seoul&arrival_city=Tokyo")
            assert MockSvc.return_value.search_flights.call_count == 1

    def test_cache_hit_skips_service(self):
        with mock.patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.return_value = _FLIGHTS_RESULT
            client.get("/search/flights?departure_city=Seoul&arrival_city=Tokyo")
            client.get("/search/flights?departure_city=Seoul&arrival_city=Tokyo")
            assert MockSvc.return_value.search_flights.call_count == 1

    def test_different_routes_miss_cache(self):
        with mock.patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.return_value = _FLIGHTS_RESULT
            client.get("/search/flights?departure_city=Seoul&arrival_city=Tokyo")
            client.get("/search/flights?departure_city=Seoul&arrival_city=Osaka")
            assert MockSvc.return_value.search_flights.call_count == 2

    def test_errors_not_cached(self):
        with mock.patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.side_effect = ValueError("no key")
            client.get("/search/flights?departure_city=Seoul&arrival_city=Tokyo")
            # Cache should be empty — error not stored
            assert search_cache.size() == 0
