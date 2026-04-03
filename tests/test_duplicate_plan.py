"""Tests for POST /travel-plans/{id}/duplicate endpoint."""
from fastapi.testclient import TestClient


PLAN_PAYLOAD = {
    "destination": "Paris, France",
    "start_date": "2026-06-01",
    "end_date": "2026-06-05",
    "budget": 3000.0,
    "interests": "art,food",
    "status": "confirmed",
}


def _create_plan(client: TestClient, payload: dict | None = None) -> dict:
    resp = client.post("/travel-plans", json=payload or PLAN_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()


def _add_day(client: TestClient, plan_id: int, date: str = "2026-06-01") -> dict:
    resp = client.post(
        f"/plans/{plan_id}/itineraries",
        json={"date": date, "notes": "Day notes", "transport": "metro", "places": []},
    )
    assert resp.status_code == 201
    return resp.json()


def _add_place(client: TestClient, plan_id: int, day_id: int) -> dict:
    resp = client.post(
        f"/plans/{plan_id}/itineraries/{day_id}/places",
        json={"name": "Eiffel Tower", "category": "sightseeing", "address": "Paris", "estimated_cost": 25.0, "order": 0},
    )
    assert resp.status_code == 201
    return resp.json()


class TestDuplicatePlan:
    def test_returns_201(self, client: TestClient):
        plan = _create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/duplicate")
        assert resp.status_code == 201

    def test_404_on_missing_plan(self, client: TestClient):
        resp = client.post("/travel-plans/9999/duplicate")
        assert resp.status_code == 404

    def test_duplicate_has_new_id(self, client: TestClient):
        plan = _create_plan(client)
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["id"] != plan["id"]

    def test_duplicate_status_is_draft(self, client: TestClient):
        plan = _create_plan(client)  # status=confirmed
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["status"] == "draft"

    def test_duplicate_copies_destination(self, client: TestClient):
        plan = _create_plan(client)
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["destination"] == plan["destination"]

    def test_duplicate_copies_dates(self, client: TestClient):
        plan = _create_plan(client)
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["start_date"] == plan["start_date"]
        assert copy["end_date"] == plan["end_date"]

    def test_duplicate_copies_budget(self, client: TestClient):
        plan = _create_plan(client)
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["budget"] == plan["budget"]

    def test_duplicate_copies_interests(self, client: TestClient):
        plan = _create_plan(client)
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["interests"] == plan["interests"]

    def test_duplicate_appears_in_list(self, client: TestClient):
        plan = _create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/duplicate")
        all_plans = client.get("/travel-plans").json()["items"]
        assert len(all_plans) == 2

    def test_original_unaffected_by_duplicate(self, client: TestClient):
        plan = _create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/duplicate")
        original = client.get(f"/travel-plans/{plan['id']}").json()
        assert original["status"] == "confirmed"  # unchanged

    def test_duplicate_with_no_itineraries(self, client: TestClient):
        plan = _create_plan(client)
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["itineraries"] == []

    def test_duplicate_copies_itineraries(self, client: TestClient):
        plan = _create_plan(client)
        _add_day(client, plan["id"], "2026-06-01")
        _add_day(client, plan["id"], "2026-06-02")
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert len(copy["itineraries"]) == 2

    def test_duplicate_itinerary_ids_differ(self, client: TestClient):
        plan = _create_plan(client)
        day = _add_day(client, plan["id"])
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["itineraries"][0]["id"] != day["id"]

    def test_duplicate_itinerary_belongs_to_copy(self, client: TestClient):
        plan = _create_plan(client)
        _add_day(client, plan["id"])
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["itineraries"][0]["travel_plan_id"] == copy["id"]

    def test_duplicate_copies_itinerary_fields(self, client: TestClient):
        plan = _create_plan(client)
        _add_day(client, plan["id"], "2026-06-01")
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        day_copy = copy["itineraries"][0]
        assert day_copy["date"] == "2026-06-01"
        assert day_copy["notes"] == "Day notes"
        assert day_copy["transport"] == "metro"

    def test_duplicate_copies_places(self, client: TestClient):
        plan = _create_plan(client)
        day = _add_day(client, plan["id"])
        _add_place(client, plan["id"], day["id"])
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert len(copy["itineraries"][0]["places"]) == 1

    def test_duplicate_place_ids_differ(self, client: TestClient):
        plan = _create_plan(client)
        day = _add_day(client, plan["id"])
        place = _add_place(client, plan["id"], day["id"])
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["itineraries"][0]["places"][0]["id"] != place["id"]

    def test_duplicate_place_fields_match(self, client: TestClient):
        plan = _create_plan(client)
        day = _add_day(client, plan["id"])
        _add_place(client, plan["id"], day["id"])
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        p = copy["itineraries"][0]["places"][0]
        assert p["name"] == "Eiffel Tower"
        assert p["category"] == "sightseeing"
        assert p["estimated_cost"] == 25.0

    def test_duplicate_expenses_not_copied(self, client: TestClient):
        plan = _create_plan(client)
        client.post(
            f"/plans/{plan['id']}/expenses",
            json={"name": "Hotel", "amount": 500.0, "category": "lodging"},
        )
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert copy["expenses"] == []

    def test_deleting_copy_does_not_affect_original(self, client: TestClient):
        plan = _create_plan(client)
        day = _add_day(client, plan["id"])
        _add_place(client, plan["id"], day["id"])
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        client.delete(f"/travel-plans/{copy['id']}")
        original = client.get(f"/travel-plans/{plan['id']}").json()
        assert len(original["itineraries"]) == 1
        assert len(original["itineraries"][0]["places"]) == 1

    def test_multiple_places_per_day_all_copied(self, client: TestClient):
        plan = _create_plan(client)
        day = _add_day(client, plan["id"])
        _add_place(client, plan["id"], day["id"])
        client.post(
            f"/plans/{plan['id']}/itineraries/{day['id']}/places",
            json={"name": "Louvre", "category": "museum", "order": 1},
        )
        copy = client.post(f"/travel-plans/{plan['id']}/duplicate").json()
        assert len(copy["itineraries"][0]["places"]) == 2
