"""Tests for place reorder endpoint (Task #23).

PATCH /plans/{plan_id}/itineraries/{day_id}/places/reorder

Covers:
- Schema: PlaceReorderRequest validation (min_length, duplicate IDs)
- Happy path: reorder all places, verify updated order fields
- Atomicity: all-or-nothing — partial lists are rejected
- Error cases: wrong plan, wrong day, extra IDs, missing IDs, duplicates
- Edge cases: single place, two-place swap
"""
import pytest
from fastapi.testclient import TestClient

from app.schemas import PlaceReorderRequest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-09-01",
    "end_date": "2026-09-03",
    "budget": 5000.0,
    "interests": "food,culture",
    "status": "draft",
}

DAY_PAYLOAD = {
    "date": "2026-09-01",
    "notes": "Day 1",
    "transport": "subway",
    "places": [],
}


def _create_plan(client: TestClient) -> int:
    r = client.post("/travel-plans", json=PLAN_PAYLOAD)
    assert r.status_code == 201
    return r.json()["id"]


def _add_day(client: TestClient, plan_id: int) -> int:
    r = client.post(f"/plans/{plan_id}/itineraries", json=DAY_PAYLOAD)
    assert r.status_code == 201
    return r.json()["id"]


def _add_place(client: TestClient, plan_id: int, day_id: int, name: str, order: int = 0) -> int:
    r = client.post(
        f"/plans/{plan_id}/itineraries/{day_id}/places",
        json={
            "name": name,
            "category": "sightseeing",
            "address": "somewhere",
            "estimated_cost": 10.0,
            "ai_reason": "",
            "order": order,
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def _reorder(client: TestClient, plan_id: int, day_id: int, place_ids: list[int]):
    return client.patch(
        f"/plans/{plan_id}/itineraries/{day_id}/places/reorder",
        json={"place_ids": place_ids},
    )


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------

class TestPlaceReorderSchema:
    def test_valid_single(self):
        r = PlaceReorderRequest(place_ids=[1])
        assert r.place_ids == [1]

    def test_valid_multiple(self):
        r = PlaceReorderRequest(place_ids=[3, 1, 2])
        assert r.place_ids == [3, 1, 2]

    def test_empty_list_rejected(self):
        import pytest as _pytest
        with _pytest.raises(Exception):
            PlaceReorderRequest(place_ids=[])

    def test_missing_place_ids_rejected(self):
        import pytest as _pytest
        with _pytest.raises(Exception):
            PlaceReorderRequest()


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def setup(client: TestClient):
    """Returns (plan_id, day_id, [p1_id, p2_id, p3_id]) with initial order 0,1,2."""
    plan_id = _create_plan(client)
    day_id = _add_day(client, plan_id)
    p1 = _add_place(client, plan_id, day_id, "Senso-ji Temple", order=0)
    p2 = _add_place(client, plan_id, day_id, "Tsukiji Market", order=1)
    p3 = _add_place(client, plan_id, day_id, "Tokyo Tower", order=2)
    return plan_id, day_id, [p1, p2, p3]


class TestReorderHappyPath:
    def test_returns_200(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [ids[2], ids[0], ids[1]])
        assert r.status_code == 200

    def test_returns_list(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [ids[2], ids[0], ids[1]])
        assert isinstance(r.json(), list)

    def test_returns_all_places(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [ids[2], ids[0], ids[1]])
        assert len(r.json()) == 3

    def test_order_values_updated(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        new_order = [ids[2], ids[0], ids[1]]
        r = _reorder(client, plan_id, day_id, new_order)
        result = {p["id"]: p["order"] for p in r.json()}
        assert result[ids[2]] == 0
        assert result[ids[0]] == 1
        assert result[ids[1]] == 2

    def test_response_sorted_by_order(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [ids[2], ids[0], ids[1]])
        orders = [p["order"] for p in r.json()]
        assert orders == sorted(orders)

    def test_first_in_list_gets_order_zero(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [ids[1], ids[0], ids[2]])
        first_place = next(p for p in r.json() if p["order"] == 0)
        assert first_place["id"] == ids[1]

    def test_persisted_after_reorder(self, client: TestClient, setup):
        """GET the day after reorder confirms persistence."""
        plan_id, day_id, ids = setup
        _reorder(client, plan_id, day_id, [ids[2], ids[1], ids[0]])
        r = client.get(f"/plans/{plan_id}/itineraries/{day_id}")
        result = {p["id"]: p["order"] for p in r.json()["places"]}
        assert result[ids[2]] == 0
        assert result[ids[1]] == 1
        assert result[ids[0]] == 2

    def test_idempotent_same_order(self, client: TestClient, setup):
        """Sending same order twice produces same result."""
        plan_id, day_id, ids = setup
        r1 = _reorder(client, plan_id, day_id, ids)
        r2 = _reorder(client, plan_id, day_id, ids)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()

    def test_place_fields_present_in_response(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, ids)
        p = r.json()[0]
        for field in ("id", "name", "category", "address", "estimated_cost", "order"):
            assert field in p


class TestReorderEdgeCases:
    def test_single_place_day(self, client: TestClient):
        plan_id = _create_plan(client)
        day_id = _add_day(client, plan_id)
        pid = _add_place(client, plan_id, day_id, "Only Place")
        r = _reorder(client, plan_id, day_id, [pid])
        assert r.status_code == 200
        assert r.json()[0]["order"] == 0

    def test_two_place_swap(self, client: TestClient):
        plan_id = _create_plan(client)
        day_id = _add_day(client, plan_id)
        p1 = _add_place(client, plan_id, day_id, "A", order=0)
        p2 = _add_place(client, plan_id, day_id, "B", order=1)
        r = _reorder(client, plan_id, day_id, [p2, p1])
        assert r.status_code == 200
        result = {p["id"]: p["order"] for p in r.json()}
        assert result[p2] == 0
        assert result[p1] == 1

    def test_reorder_does_not_affect_other_days(self, client: TestClient):
        """Places on a sibling day are unaffected by reorder."""
        plan_id = _create_plan(client)
        day1 = _add_day(client, plan_id)
        day2_id = client.post(
            f"/plans/{plan_id}/itineraries",
            json={"date": "2026-09-02", "notes": "", "transport": "", "places": []},
        ).json()["id"]
        p_day1 = _add_place(client, plan_id, day1, "Day1 Place")
        p_day2 = _add_place(client, plan_id, day2_id, "Day2 Place", order=0)
        _reorder(client, plan_id, day1, [p_day1])
        r = client.get(f"/plans/{plan_id}/itineraries/{day2_id}")
        assert r.json()["places"][0]["id"] == p_day2


class TestReorderValidationErrors:
    def test_extra_place_id_rejected(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, ids + [99999])
        assert r.status_code == 422

    def test_missing_place_id_rejected(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, ids[:2])  # omit last
        assert r.status_code == 422

    def test_duplicate_ids_rejected(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [ids[0], ids[0], ids[1]])
        assert r.status_code == 422

    def test_empty_list_rejected(self, client: TestClient, setup):
        plan_id, day_id, ids = setup
        r = _reorder(client, plan_id, day_id, [])
        assert r.status_code == 422

    def test_wrong_day_place_ids_rejected(self, client: TestClient):
        """Place IDs from a different day are rejected."""
        plan_id = _create_plan(client)
        day1 = _add_day(client, plan_id)
        day2 = client.post(
            f"/plans/{plan_id}/itineraries",
            json={"date": "2026-09-02", "notes": "", "transport": "", "places": []},
        ).json()["id"]
        _add_place(client, plan_id, day1, "Place on day 1")
        p_day2 = _add_place(client, plan_id, day2, "Place on day 2")
        # reorder day1 but pass day2's place — should be rejected
        r = _reorder(client, plan_id, day1, [p_day2])
        assert r.status_code == 422


class TestReorderNotFound:
    def test_nonexistent_plan_returns_404(self, client: TestClient):
        r = _reorder(client, 99999, 1, [1])
        assert r.status_code == 404

    def test_nonexistent_day_returns_404(self, client: TestClient):
        plan_id = _create_plan(client)
        r = _reorder(client, plan_id, 99999, [1])
        assert r.status_code == 404

    def test_day_belonging_to_different_plan_returns_404(self, client: TestClient):
        plan1 = _create_plan(client)
        plan2 = _create_plan(client)
        day_id = _add_day(client, plan2)
        p = _add_place(client, plan2, day_id, "Some Place")
        r = _reorder(client, plan1, day_id, [p])
        assert r.status_code == 404
