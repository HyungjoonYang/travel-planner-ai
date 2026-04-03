"""Tests for pagination on GET /travel-plans (#25).

Covers:
- Response envelope shape: items, total, page, page_size, pages
- Empty DB metadata (total=0, pages=1)
- Default page/page_size values
- page and page_size params: slicing, ordering preserved
- page_size boundary validation (ge=1, le=100)
- page boundary validation (ge=1)
- Last page may have fewer items than page_size
- page beyond total pages returns empty items but correct metadata
- page_size=1 edge case
- Filters compose with pagination (total reflects filtered count)
"""



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = {
    "start_date": "2026-07-01",
    "end_date": "2026-07-05",
    "budget": 1000,
    "interests": "",
    "status": "draft",
}


def make_plan(client, destination: str, **overrides) -> dict:
    payload = {**_BASE, "destination": destination, **overrides}
    r = client.post("/travel-plans", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def make_plans(client, n: int) -> list[dict]:
    """Create n plans with destinations City_1 … City_n."""
    return [make_plan(client, f"City_{i + 1}") for i in range(n)]


# ---------------------------------------------------------------------------
# Response envelope shape
# ---------------------------------------------------------------------------

class TestResponseShape:
    def test_has_items_key(self, client):
        r = client.get("/travel-plans")
        assert "items" in r.json()

    def test_has_total_key(self, client):
        r = client.get("/travel-plans")
        assert "total" in r.json()

    def test_has_page_key(self, client):
        r = client.get("/travel-plans")
        assert "page" in r.json()

    def test_has_page_size_key(self, client):
        r = client.get("/travel-plans")
        assert "page_size" in r.json()

    def test_has_pages_key(self, client):
        r = client.get("/travel-plans")
        assert "pages" in r.json()

    def test_items_is_list(self, client):
        r = client.get("/travel-plans")
        assert isinstance(r.json()["items"], list)


# ---------------------------------------------------------------------------
# Empty DB metadata
# ---------------------------------------------------------------------------

class TestEmptyDB:
    def test_total_is_zero(self, client):
        assert client.get("/travel-plans").json()["total"] == 0

    def test_pages_is_one(self, client):
        # at least 1 page even when empty
        assert client.get("/travel-plans").json()["pages"] == 1

    def test_items_is_empty(self, client):
        assert client.get("/travel-plans").json()["items"] == []

    def test_page_defaults_to_one(self, client):
        assert client.get("/travel-plans").json()["page"] == 1

    def test_page_size_defaults_to_twenty(self, client):
        assert client.get("/travel-plans").json()["page_size"] == 20


# ---------------------------------------------------------------------------
# Default pagination (page=1, page_size=20)
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_total_matches_created_count(self, client):
        make_plans(client, 3)
        assert client.get("/travel-plans").json()["total"] == 3

    def test_pages_calculated_correctly(self, client):
        make_plans(client, 25)
        data = client.get("/travel-plans").json()
        # 25 items / 20 per page = 2 pages
        assert data["pages"] == 2

    def test_first_page_has_twenty_items(self, client):
        make_plans(client, 25)
        data = client.get("/travel-plans").json()
        assert len(data["items"]) == 20

    def test_single_page_when_under_limit(self, client):
        make_plans(client, 5)
        data = client.get("/travel-plans").json()
        assert data["pages"] == 1
        assert len(data["items"]) == 5


# ---------------------------------------------------------------------------
# Explicit page / page_size params
# ---------------------------------------------------------------------------

class TestPageParam:
    def test_page_two_returns_remaining(self, client):
        make_plans(client, 25)
        data = client.get("/travel-plans?page=2").json()
        assert len(data["items"]) == 5  # 25 - 20

    def test_page_reflects_requested_value(self, client):
        make_plans(client, 25)
        assert client.get("/travel-plans?page=2").json()["page"] == 2

    def test_page_beyond_total_returns_empty_items(self, client):
        make_plans(client, 3)
        data = client.get("/travel-plans?page=99").json()
        assert data["items"] == []
        assert data["total"] == 3

    def test_page_zero_returns_422(self, client):
        assert client.get("/travel-plans?page=0").status_code == 422

    def test_page_negative_returns_422(self, client):
        assert client.get("/travel-plans?page=-1").status_code == 422


class TestPageSizeParam:
    def test_page_size_one_returns_one_item(self, client):
        make_plans(client, 5)
        data = client.get("/travel-plans?page_size=1").json()
        assert len(data["items"]) == 1

    def test_page_size_one_pages_equals_total(self, client):
        make_plans(client, 5)
        data = client.get("/travel-plans?page_size=1").json()
        assert data["pages"] == 5

    def test_page_size_reflects_requested_value(self, client):
        make_plans(client, 5)
        assert client.get("/travel-plans?page_size=3").json()["page_size"] == 3

    def test_page_size_larger_than_total_returns_all(self, client):
        make_plans(client, 3)
        data = client.get("/travel-plans?page_size=100").json()
        assert len(data["items"]) == 3

    def test_page_size_zero_returns_422(self, client):
        assert client.get("/travel-plans?page_size=0").status_code == 422

    def test_page_size_101_returns_422(self, client):
        assert client.get("/travel-plans?page_size=101").status_code == 422

    def test_page_size_100_is_valid(self, client):
        assert client.get("/travel-plans?page_size=100").status_code == 200


# ---------------------------------------------------------------------------
# Ordering preserved across pages
# ---------------------------------------------------------------------------

class TestOrderingAcrossPages:
    def test_second_page_continues_from_first(self, client):
        plans = make_plans(client, 5)
        # Default sort is created_at DESC → most recently created first
        p1 = client.get("/travel-plans?page_size=3&page=1").json()["items"]
        p2 = client.get("/travel-plans?page_size=3&page=2").json()["items"]
        all_ids = [p["id"] for p in p1] + [p["id"] for p in p2]
        # No duplicates, all 5 unique IDs covered
        assert len(set(all_ids)) == 5
        assert set(all_ids) == {p["id"] for p in plans}

    def test_pages_are_disjoint(self, client):
        make_plans(client, 6)
        p1_ids = {p["id"] for p in client.get("/travel-plans?page_size=3&page=1").json()["items"]}
        p2_ids = {p["id"] for p in client.get("/travel-plans?page_size=3&page=2").json()["items"]}
        assert p1_ids.isdisjoint(p2_ids)


# ---------------------------------------------------------------------------
# Filters compose with pagination
# ---------------------------------------------------------------------------

class TestFiltersWithPagination:
    def test_total_reflects_filtered_count(self, client):
        make_plan(client, "Tokyo")
        make_plan(client, "Paris")
        make_plan(client, "Tokyo2")
        data = client.get("/travel-plans?destination=Tokyo").json()
        assert data["total"] == 2

    def test_pages_reflect_filtered_count(self, client):
        for i in range(25):
            make_plan(client, "Tokyo")
        make_plan(client, "Paris")
        data = client.get("/travel-plans?destination=Paris").json()
        assert data["total"] == 1
        assert data["pages"] == 1

    def test_filtered_pagination_slices_correctly(self, client):
        for i in range(5):
            make_plan(client, "Tokyo")
        make_plan(client, "Paris")
        data = client.get("/travel-plans?destination=Tokyo&page_size=3&page=1").json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["pages"] == 2

    def test_status_filter_total(self, client):
        make_plan(client, "Tokyo", status="draft")
        make_plan(client, "Paris", status="confirmed")
        assert client.get("/travel-plans?status=draft").json()["total"] == 1
        assert client.get("/travel-plans?status=confirmed").json()["total"] == 1
