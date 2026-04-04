"""Tests for manual itinerary editing endpoints (Task #21).

Covers:
- DayItinerary: POST, GET list, GET single, PATCH, DELETE
- Place: POST, PATCH, DELETE (nested under a day)
- 404 behaviour for missing plan / day / place
- Schema validation for DayItineraryUpdate and PlaceUpdate
"""
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Paris",
    "start_date": "2026-07-01",
    "end_date": "2026-07-05",
    "budget": 3000.0,
    "interests": "art,food",
    "status": "draft",
}

DAY_PAYLOAD = {
    "date": "2026-07-01",
    "notes": "Arrival day",
    "transport": "CDG → hotel taxi",
    "places": [],
}

PLACE_PAYLOAD = {
    "name": "Eiffel Tower",
    "category": "sightseeing",
    "address": "Champ de Mars, 75007 Paris",
    "estimated_cost": 25.0,
    "ai_reason": "Iconic landmark",
    "order": 1,
}


def _create_plan(client: TestClient) -> int:
    r = client.post("/travel-plans", json=PLAN_PAYLOAD)
    assert r.status_code == 201
    return r.json()["id"]


def _add_day(client: TestClient, plan_id: int, payload: dict | None = None) -> dict:
    data = payload or DAY_PAYLOAD
    r = client.post(f"/plans/{plan_id}/itineraries", json=data)
    assert r.status_code == 201
    return r.json()


def _add_place(client: TestClient, plan_id: int, day_id: int, payload: dict | None = None) -> dict:
    data = payload or PLACE_PAYLOAD
    r = client.post(f"/plans/{plan_id}/itineraries/{day_id}/places", json=data)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# DayItinerary — schema unit tests (no HTTP)
# ---------------------------------------------------------------------------

class TestDayItinerarySchemas:
    def test_update_all_fields_optional(self):
        from app.schemas import DayItineraryUpdate
        u = DayItineraryUpdate()
        assert u.date is None
        assert u.notes is None
        assert u.transport is None

    def test_update_accepts_partial(self):
        from app.schemas import DayItineraryUpdate
        u = DayItineraryUpdate(notes="updated notes")
        assert u.notes == "updated notes"
        assert u.date is None

    def test_create_requires_date(self):
        from pydantic import ValidationError
        from app.schemas import DayItineraryCreate
        with pytest.raises(ValidationError):
            DayItineraryCreate()

    def test_create_accepts_places_list(self):
        from app.schemas import DayItineraryCreate, PlaceCreate
        day = DayItineraryCreate(
            date="2026-07-01",
            places=[PlaceCreate(name="Louvre", order=0)],
        )
        assert len(day.places) == 1


# ---------------------------------------------------------------------------
# Place — schema unit tests
# ---------------------------------------------------------------------------

class TestPlaceSchemas:
    def test_update_all_fields_optional(self):
        from app.schemas import PlaceUpdate
        u = PlaceUpdate()
        assert u.name is None
        assert u.estimated_cost is None

    def test_update_name_min_length(self):
        from pydantic import ValidationError
        from app.schemas import PlaceUpdate
        with pytest.raises(ValidationError):
            PlaceUpdate(name="")

    def test_update_estimated_cost_ge_zero(self):
        from pydantic import ValidationError
        from app.schemas import PlaceUpdate
        with pytest.raises(ValidationError):
            PlaceUpdate(estimated_cost=-1.0)

    def test_update_order_ge_zero(self):
        from pydantic import ValidationError
        from app.schemas import PlaceUpdate
        with pytest.raises(ValidationError):
            PlaceUpdate(order=-1)


# ---------------------------------------------------------------------------
# DayItinerary HTTP — POST /plans/{id}/itineraries
# ---------------------------------------------------------------------------

class TestAddDay:
    def test_returns_201(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/itineraries", json=DAY_PAYLOAD)
        assert r.status_code == 201

    def test_response_has_id(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        assert "id" in day

    def test_response_fields(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        assert day["date"] == DAY_PAYLOAD["date"]
        assert day["notes"] == DAY_PAYLOAD["notes"]
        assert day["transport"] == DAY_PAYLOAD["transport"]
        assert day["travel_plan_id"] == plan_id

    def test_places_inline(self, client):
        plan_id = _create_plan(client)
        payload = {**DAY_PAYLOAD, "places": [PLACE_PAYLOAD]}
        r = client.post(f"/plans/{plan_id}/itineraries", json=payload)
        assert r.status_code == 201
        assert len(r.json()["places"]) == 1
        assert r.json()["places"][0]["name"] == "Eiffel Tower"

    def test_404_when_plan_missing(self, client):
        r = client.post("/plans/9999/itineraries", json=DAY_PAYLOAD)
        assert r.status_code == 404

    def test_422_when_date_missing(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/itineraries", json={"notes": "no date"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# DayItinerary HTTP — GET /plans/{id}/itineraries
# ---------------------------------------------------------------------------

class TestListDays:
    def test_empty_list_initially(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/itineraries")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_added_day(self, client):
        plan_id = _create_plan(client)
        _add_day(client, plan_id)
        r = client.get(f"/plans/{plan_id}/itineraries")
        assert len(r.json()) == 1

    def test_ordered_by_date(self, client):
        plan_id = _create_plan(client)
        _add_day(client, plan_id, {**DAY_PAYLOAD, "date": "2026-07-03"})
        _add_day(client, plan_id, {**DAY_PAYLOAD, "date": "2026-07-01"})
        days = client.get(f"/plans/{plan_id}/itineraries").json()
        assert days[0]["date"] == "2026-07-01"
        assert days[1]["date"] == "2026-07-03"

    def test_404_when_plan_missing(self, client):
        r = client.get("/plans/9999/itineraries")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DayItinerary HTTP — GET single day
# ---------------------------------------------------------------------------

class TestGetDay:
    def test_returns_200(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}")
        assert r.status_code == 200

    def test_returns_correct_day(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}")
        assert r.json()["id"] == day["id"]

    def test_404_wrong_plan(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        other_plan = _create_plan(client)
        r = client.get(f"/plans/{other_plan}/itineraries/{day['id']}")
        assert r.status_code == 404

    def test_404_missing_day(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/itineraries/9999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DayItinerary HTTP — PATCH
# ---------------------------------------------------------------------------

class TestUpdateDay:
    def test_update_notes(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}",
            json={"notes": "Updated notes"},
        )
        assert r.status_code == 200
        assert r.json()["notes"] == "Updated notes"

    def test_update_transport(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}",
            json={"transport": "Metro"},
        )
        assert r.json()["transport"] == "Metro"

    def test_update_date(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}",
            json={"date": "2026-07-02"},
        )
        assert r.json()["date"] == "2026-07-02"

    def test_partial_update_keeps_other_fields(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}",
            json={"notes": "Only notes changed"},
        )
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}")
        assert r.json()["transport"] == DAY_PAYLOAD["transport"]

    def test_404_missing_day(self, client):
        plan_id = _create_plan(client)
        r = client.patch(f"/plans/{plan_id}/itineraries/9999", json={"notes": "x"})
        assert r.status_code == 404

    def test_404_wrong_plan(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        other = _create_plan(client)
        r = client.patch(
            f"/plans/{other}/itineraries/{day['id']}",
            json={"notes": "x"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DayItinerary HTTP — DELETE
# ---------------------------------------------------------------------------

class TestDeleteDay:
    def test_returns_204(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.delete(f"/plans/{plan_id}/itineraries/{day['id']}")
        assert r.status_code == 204

    def test_day_no_longer_listed(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        client.delete(f"/plans/{plan_id}/itineraries/{day['id']}")
        r = client.get(f"/plans/{plan_id}/itineraries")
        assert r.json() == []

    def test_places_cascade_deleted(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        _add_place(client, plan_id, day["id"])
        client.delete(f"/plans/{plan_id}/itineraries/{day['id']}")
        # Recreate the day and verify old place is gone
        new_day = _add_day(client, plan_id)
        assert new_day["places"] == []

    def test_404_missing_day(self, client):
        plan_id = _create_plan(client)
        r = client.delete(f"/plans/{plan_id}/itineraries/9999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Place HTTP — POST /plans/{id}/itineraries/{day_id}/places
# ---------------------------------------------------------------------------

class TestAddPlace:
    def test_returns_201(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.post(f"/plans/{plan_id}/itineraries/{day['id']}/places", json=PLACE_PAYLOAD)
        assert r.status_code == 201

    def test_response_fields(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        assert place["name"] == PLACE_PAYLOAD["name"]
        assert place["category"] == PLACE_PAYLOAD["category"]
        assert place["estimated_cost"] == PLACE_PAYLOAD["estimated_cost"]
        assert place["day_itinerary_id"] == day["id"]

    def test_place_appears_in_day(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        _add_place(client, plan_id, day["id"])
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}")
        assert len(r.json()["places"]) == 1

    def test_404_wrong_plan(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        other = _create_plan(client)
        r = client.post(f"/plans/{other}/itineraries/{day['id']}/places", json=PLACE_PAYLOAD)
        assert r.status_code == 404

    def test_404_missing_day(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/itineraries/9999/places", json=PLACE_PAYLOAD)
        assert r.status_code == 404

    def test_422_missing_name(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.post(
            f"/plans/{plan_id}/itineraries/{day['id']}/places",
            json={"category": "food"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Place HTTP — PATCH
# ---------------------------------------------------------------------------

class TestUpdatePlace:
    def test_update_name(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}",
            json={"name": "Louvre Museum"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Louvre Museum"

    def test_update_cost(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}",
            json={"estimated_cost": 50.0},
        )
        assert r.json()["estimated_cost"] == 50.0

    def test_update_order(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}",
            json={"order": 3},
        )
        assert r.json()["order"] == 3

    def test_partial_keeps_other_fields(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}",
            json={"name": "New Name"},
        )
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}",
            json={},
        )
        assert r.json()["category"] == PLACE_PAYLOAD["category"]

    def test_404_missing_place(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/9999",
            json={"name": "x"},
        )
        assert r.status_code == 404

    def test_404_wrong_day(self, client):
        plan_id = _create_plan(client)
        day1 = _add_day(client, plan_id, {**DAY_PAYLOAD, "date": "2026-07-01"})
        day2 = _add_day(client, plan_id, {**DAY_PAYLOAD, "date": "2026-07-02"})
        place = _add_place(client, plan_id, day1["id"])
        r = client.patch(
            f"/plans/{plan_id}/itineraries/{day2['id']}/places/{place['id']}",
            json={"name": "x"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Place HTTP — DELETE
# ---------------------------------------------------------------------------

class TestDeletePlace:
    def test_returns_204(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        r = client.delete(
            f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}"
        )
        assert r.status_code == 204

    def test_place_removed_from_day(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        place = _add_place(client, plan_id, day["id"])
        client.delete(f"/plans/{plan_id}/itineraries/{day['id']}/places/{place['id']}")
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}")
        assert r.json()["places"] == []

    def test_404_missing_place(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.delete(f"/plans/{plan_id}/itineraries/{day['id']}/places/9999")
        assert r.status_code == 404

    def test_404_wrong_day(self, client):
        plan_id = _create_plan(client)
        day1 = _add_day(client, plan_id, {**DAY_PAYLOAD, "date": "2026-07-01"})
        day2 = _add_day(client, plan_id, {**DAY_PAYLOAD, "date": "2026-07-02"})
        place = _add_place(client, plan_id, day1["id"])
        r = client.delete(
            f"/plans/{plan_id}/itineraries/{day2['id']}/places/{place['id']}"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Integration — plan-level view reflects manual changes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DayStats — GET /plans/{id}/itineraries/{day_id}/stats
# ---------------------------------------------------------------------------

class TestDayStats:
    def test_returns_200(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}/stats")
        assert r.status_code == 200

    def test_empty_day_zero_cost(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}/stats")
        data = r.json()
        assert data["place_count"] == 0
        assert data["total_estimated_cost"] == 0.0
        assert data["by_category"] == {}

    def test_place_count(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        _add_place(client, plan_id, day["id"])
        _add_place(client, plan_id, day["id"], {**PLACE_PAYLOAD, "name": "Louvre"})
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}/stats")
        assert r.json()["place_count"] == 2

    def test_total_estimated_cost(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        _add_place(client, plan_id, day["id"], {**PLACE_PAYLOAD, "estimated_cost": 30.0})
        _add_place(client, plan_id, day["id"], {**PLACE_PAYLOAD, "name": "Louvre", "estimated_cost": 20.0})
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}/stats")
        assert r.json()["total_estimated_cost"] == 50.0

    def test_category_breakdown(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        _add_place(client, plan_id, day["id"], {**PLACE_PAYLOAD, "category": "sightseeing", "estimated_cost": 25.0})
        _add_place(client, plan_id, day["id"], {**PLACE_PAYLOAD, "name": "Café de Flore", "category": "food", "estimated_cost": 40.0})
        _add_place(client, plan_id, day["id"], {**PLACE_PAYLOAD, "name": "Louvre", "category": "sightseeing", "estimated_cost": 15.0})
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}/stats")
        data = r.json()
        assert data["by_category"]["sightseeing"] == 40.0
        assert data["by_category"]["food"] == 40.0

    def test_response_has_day_id(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        r = client.get(f"/plans/{plan_id}/itineraries/{day['id']}/stats")
        assert r.json()["day_id"] == day["id"]

    def test_404_missing_day(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/itineraries/9999/stats")
        assert r.status_code == 404

    def test_404_wrong_plan(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        other = _create_plan(client)
        r = client.get(f"/plans/{other}/itineraries/{day['id']}/stats")
        assert r.status_code == 404

    def test_404_missing_plan(self, client):
        r = client.get("/plans/9999/itineraries/1/stats")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Integration — plan-level view reflects manual changes
# ---------------------------------------------------------------------------

class TestPlanReflectsManualEdits:
    def test_plan_detail_shows_new_day(self, client):
        plan_id = _create_plan(client)
        _add_day(client, plan_id)
        r = client.get(f"/travel-plans/{plan_id}")
        assert len(r.json()["itineraries"]) == 1

    def test_plan_detail_shows_new_place(self, client):
        plan_id = _create_plan(client)
        day = _add_day(client, plan_id)
        _add_place(client, plan_id, day["id"])
        r = client.get(f"/travel-plans/{plan_id}")
        assert len(r.json()["itineraries"][0]["places"]) == 1

    def test_multiple_plans_isolated(self, client):
        plan1 = _create_plan(client)
        plan2 = _create_plan(client)
        _add_day(client, plan1)
        r = client.get(f"/plans/{plan2}/itineraries")
        assert r.json() == []
