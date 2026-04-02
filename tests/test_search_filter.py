"""Tests for GET /travel-plans search & filter query params (#24).

Covers:
- No filters → returns all plans (existing behaviour preserved)
- destination: partial, case-insensitive match; no match returns []
- status: exact match draft/confirmed; invalid value → 422
- from / to date range on start_date; combined range
- Multiple filters combined
- Sort order: created_at DESC (most-recent first)
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = {
    "start_date": "2026-06-01",
    "end_date": "2026-06-05",
    "budget": 1000,
    "interests": "food",
    "status": "draft",
}


def make_plan(client, destination: str, start_date: str = "2026-06-01",
              end_date: str = "2026-06-05", status: str = "draft",
              budget: float = 1000) -> dict:
    payload = {
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "budget": budget,
        "interests": "",
        "status": status,
    }
    r = client.post("/travel-plans", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# No-filter baseline
# ---------------------------------------------------------------------------

class TestListNoFilter:
    def test_empty_db_returns_empty_list(self, client):
        r = client.get("/travel-plans")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_all_plans(self, client):
        make_plan(client, "Tokyo")
        make_plan(client, "Paris")
        r = client.get("/travel-plans")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_sorted_by_created_at_desc(self, client):
        p1 = make_plan(client, "Tokyo")
        p2 = make_plan(client, "Paris")
        plans = client.get("/travel-plans").json()
        # most-recently created appears first
        assert plans[0]["id"] == p2["id"]
        assert plans[1]["id"] == p1["id"]


# ---------------------------------------------------------------------------
# destination filter
# ---------------------------------------------------------------------------

class TestDestinationFilter:
    def test_exact_match(self, client):
        make_plan(client, "Tokyo")
        make_plan(client, "Paris")
        plans = client.get("/travel-plans?destination=Tokyo").json()
        assert len(plans) == 1
        assert plans[0]["destination"] == "Tokyo"

    def test_partial_match(self, client):
        make_plan(client, "New York City")
        make_plan(client, "New Delhi")
        make_plan(client, "London")
        plans = client.get("/travel-plans?destination=New").json()
        destinations = {p["destination"] for p in plans}
        assert destinations == {"New York City", "New Delhi"}

    def test_case_insensitive_lower(self, client):
        make_plan(client, "Tokyo")
        plans = client.get("/travel-plans?destination=tokyo").json()
        assert len(plans) == 1

    def test_case_insensitive_upper(self, client):
        make_plan(client, "Tokyo")
        plans = client.get("/travel-plans?destination=TOKYO").json()
        assert len(plans) == 1

    def test_case_insensitive_mixed(self, client):
        make_plan(client, "Tokyo")
        plans = client.get("/travel-plans?destination=tOkYo").json()
        assert len(plans) == 1

    def test_no_match_returns_empty(self, client):
        make_plan(client, "Tokyo")
        plans = client.get("/travel-plans?destination=Berlin").json()
        assert plans == []

    def test_empty_destination_matches_all(self, client):
        make_plan(client, "Tokyo")
        make_plan(client, "Paris")
        # empty string → ilike "%%" matches everything
        plans = client.get("/travel-plans?destination=").json()
        assert len(plans) == 2


# ---------------------------------------------------------------------------
# status filter
# ---------------------------------------------------------------------------

class TestStatusFilter:
    def test_filter_draft(self, client):
        make_plan(client, "Tokyo", status="draft")
        make_plan(client, "Paris", status="confirmed")
        plans = client.get("/travel-plans?status=draft").json()
        assert all(p["status"] == "draft" for p in plans)
        assert len(plans) == 1

    def test_filter_confirmed(self, client):
        make_plan(client, "Tokyo", status="draft")
        make_plan(client, "Paris", status="confirmed")
        plans = client.get("/travel-plans?status=confirmed").json()
        assert all(p["status"] == "confirmed" for p in plans)
        assert len(plans) == 1

    def test_no_match_returns_empty(self, client):
        make_plan(client, "Tokyo", status="draft")
        plans = client.get("/travel-plans?status=confirmed").json()
        assert plans == []

    def test_invalid_status_returns_422(self, client):
        r = client.get("/travel-plans?status=unknown")
        assert r.status_code == 422

    def test_both_statuses_returned_without_filter(self, client):
        make_plan(client, "Tokyo", status="draft")
        make_plan(client, "Paris", status="confirmed")
        plans = client.get("/travel-plans").json()
        statuses = {p["status"] for p in plans}
        assert statuses == {"draft", "confirmed"}


# ---------------------------------------------------------------------------
# date-range filter (from / to on start_date)
# ---------------------------------------------------------------------------

class TestDateRangeFilter:
    def test_from_filter_includes_equal_date(self, client):
        make_plan(client, "Tokyo", start_date="2026-06-01", end_date="2026-06-05")
        plans = client.get("/travel-plans?from=2026-06-01").json()
        assert len(plans) == 1

    def test_from_filter_excludes_earlier(self, client):
        make_plan(client, "Tokyo", start_date="2026-05-01", end_date="2026-05-05")
        plans = client.get("/travel-plans?from=2026-06-01").json()
        assert plans == []

    def test_to_filter_includes_equal_date(self, client):
        make_plan(client, "Tokyo", start_date="2026-06-01", end_date="2026-06-05")
        plans = client.get("/travel-plans?to=2026-06-01").json()
        assert len(plans) == 1

    def test_to_filter_excludes_later(self, client):
        make_plan(client, "Tokyo", start_date="2026-07-01", end_date="2026-07-05")
        plans = client.get("/travel-plans?to=2026-06-30").json()
        assert plans == []

    def test_from_to_range_selects_correct_plans(self, client):
        make_plan(client, "Tokyo",   start_date="2026-05-01", end_date="2026-05-05")
        make_plan(client, "Paris",   start_date="2026-06-15", end_date="2026-06-20")
        make_plan(client, "London",  start_date="2026-07-01", end_date="2026-07-05")
        plans = client.get("/travel-plans?from=2026-06-01&to=2026-06-30").json()
        assert len(plans) == 1
        assert plans[0]["destination"] == "Paris"

    def test_from_to_range_includes_boundaries(self, client):
        make_plan(client, "Tokyo",  start_date="2026-06-01", end_date="2026-06-05")
        make_plan(client, "Paris",  start_date="2026-06-30", end_date="2026-07-04")
        plans = client.get("/travel-plans?from=2026-06-01&to=2026-06-30").json()
        assert len(plans) == 2

    def test_invalid_date_format_returns_422(self, client):
        r = client.get("/travel-plans?from=not-a-date")
        assert r.status_code == 422

    def test_invalid_to_date_format_returns_422(self, client):
        r = client.get("/travel-plans?to=2026-13-01")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------

class TestCombinedFilters:
    def test_destination_and_status(self, client):
        make_plan(client, "Tokyo", status="draft")
        make_plan(client, "Tokyo", status="confirmed")
        make_plan(client, "Paris", status="draft")
        plans = client.get("/travel-plans?destination=Tokyo&status=draft").json()
        assert len(plans) == 1
        assert plans[0]["destination"] == "Tokyo"
        assert plans[0]["status"] == "draft"

    def test_destination_and_date_range(self, client):
        make_plan(client, "Tokyo", start_date="2026-06-15", end_date="2026-06-20")
        make_plan(client, "Tokyo", start_date="2026-08-01", end_date="2026-08-05")
        make_plan(client, "Paris", start_date="2026-06-15", end_date="2026-06-20")
        plans = client.get("/travel-plans?destination=Tokyo&from=2026-06-01&to=2026-07-01").json()
        assert len(plans) == 1
        assert plans[0]["destination"] == "Tokyo"

    def test_all_three_filters(self, client):
        make_plan(client, "Tokyo", start_date="2026-06-15", end_date="2026-06-20", status="confirmed")
        make_plan(client, "Tokyo", start_date="2026-06-15", end_date="2026-06-20", status="draft")
        make_plan(client, "Paris", start_date="2026-06-15", end_date="2026-06-20", status="confirmed")
        plans = client.get(
            "/travel-plans?destination=Tokyo&status=confirmed&from=2026-06-01&to=2026-07-01"
        ).json()
        assert len(plans) == 1
        assert plans[0]["destination"] == "Tokyo"
        assert plans[0]["status"] == "confirmed"

    def test_no_matches_with_combined(self, client):
        make_plan(client, "Tokyo", status="draft")
        plans = client.get("/travel-plans?destination=Tokyo&status=confirmed").json()
        assert plans == []
