"""Tests for GET /travel-plans/{id}/export endpoint."""
import pytest
from fastapi.testclient import TestClient


# --- fixtures -----------------------------------------------------------

@pytest.fixture
def plan(client: TestClient):
    resp = client.post("/travel-plans", json={
        "destination": "Tokyo",
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
        "budget": 2000.0,
        "interests": "food, culture",
        "notes": "Golden Week trip",
    })
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
def plan_with_itinerary(client: TestClient, plan):
    """Plan with one day itinerary + two places."""
    day_resp = client.post(
        f"/plans/{plan['id']}/itineraries",
        json={"date": "2026-05-01", "transport": "subway", "notes": "arrival day"},
    )
    assert day_resp.status_code == 201
    day = day_resp.json()

    client.post(
        f"/plans/{plan['id']}/itineraries/{day['id']}/places",
        json={"name": "Senso-ji", "category": "temple", "estimated_cost": 0.0},
    )
    client.post(
        f"/plans/{plan['id']}/itineraries/{day['id']}/places",
        json={"name": "Asakusa Street Food", "category": "food", "estimated_cost": 15.0},
    )
    return plan


@pytest.fixture
def plan_with_expenses(client: TestClient, plan):
    """Plan with two expenses."""
    client.post(
        f"/plans/{plan['id']}/expenses",
        json={"name": "Flight", "amount": 800.0, "category": "transport"},
    )
    client.post(
        f"/plans/{plan['id']}/expenses",
        json={"name": "Hotel", "amount": 600.0, "category": "accommodation"},
    )
    return plan


# --- status code tests --------------------------------------------------

class TestExportStatusCode:
    def test_existing_plan_returns_200(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.status_code == 200

    def test_missing_plan_returns_404(self, client: TestClient):
        resp = client.get("/travel-plans/99999/export")
        assert resp.status_code == 404

    def test_404_detail_message(self, client: TestClient):
        resp = client.get("/travel-plans/99999/export")
        assert resp.json()["detail"] == "Travel plan not found"


# --- Content-Disposition header tests -----------------------------------

class TestExportHeaders:
    def test_content_disposition_is_attachment(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd

    def test_filename_contains_plan_id(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        cd = resp.headers.get("content-disposition", "")
        assert f"travel-plan-{plan['id']}.json" in cd

    def test_content_type_is_json(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert "application/json" in resp.headers.get("content-type", "")


# --- Response body shape tests ------------------------------------------

class TestExportBodyShape:
    def test_body_is_valid_json(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        data = resp.json()
        assert isinstance(data, dict)

    def test_body_has_id(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["id"] == plan["id"]

    def test_body_has_destination(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["destination"] == "Tokyo"

    def test_body_has_start_date(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["start_date"] == "2026-05-01"

    def test_body_has_end_date(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["end_date"] == "2026-05-05"

    def test_body_has_budget(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["budget"] == 2000.0

    def test_body_has_interests(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["interests"] == "food, culture"

    def test_body_has_notes(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["notes"] == "Golden Week trip"

    def test_body_has_status(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert resp.json()["status"] == "draft"

    def test_body_has_created_at(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert "created_at" in resp.json()

    def test_body_has_updated_at(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert "updated_at" in resp.json()

    def test_body_has_itineraries_list(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert isinstance(resp.json()["itineraries"], list)

    def test_body_has_expenses_list(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert isinstance(resp.json()["expenses"], list)


# --- Nested data tests --------------------------------------------------

class TestExportNestedItineraries:
    def test_itineraries_count(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        assert len(resp.json()["itineraries"]) == 1

    def test_itinerary_date(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        day = resp.json()["itineraries"][0]
        assert day["date"] == "2026-05-01"

    def test_itinerary_transport(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        day = resp.json()["itineraries"][0]
        assert day["transport"] == "subway"

    def test_itinerary_notes(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        day = resp.json()["itineraries"][0]
        assert day["notes"] == "arrival day"

    def test_places_count(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        places = resp.json()["itineraries"][0]["places"]
        assert len(places) == 2

    def test_place_name(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        names = [p["name"] for p in resp.json()["itineraries"][0]["places"]]
        assert "Senso-ji" in names

    def test_place_category(self, client: TestClient, plan_with_itinerary):
        resp = client.get(f"/travel-plans/{plan_with_itinerary['id']}/export")
        senso = next(p for p in resp.json()["itineraries"][0]["places"] if p["name"] == "Senso-ji")
        assert senso["category"] == "temple"


class TestExportNestedExpenses:
    def test_expenses_count(self, client: TestClient, plan_with_expenses):
        resp = client.get(f"/travel-plans/{plan_with_expenses['id']}/export")
        assert len(resp.json()["expenses"]) == 2

    def test_expense_names(self, client: TestClient, plan_with_expenses):
        resp = client.get(f"/travel-plans/{plan_with_expenses['id']}/export")
        names = [e["name"] for e in resp.json()["expenses"]]
        assert "Flight" in names
        assert "Hotel" in names

    def test_expense_amount(self, client: TestClient, plan_with_expenses):
        resp = client.get(f"/travel-plans/{plan_with_expenses['id']}/export")
        flight = next(e for e in resp.json()["expenses"] if e["name"] == "Flight")
        assert flight["amount"] == 800.0

    def test_expense_category(self, client: TestClient, plan_with_expenses):
        resp = client.get(f"/travel-plans/{plan_with_expenses['id']}/export")
        hotel = next(e for e in resp.json()["expenses"] if e["name"] == "Hotel")
        assert hotel["category"] == "accommodation"


# --- Serialization tests ------------------------------------------------

class TestExportSerialization:
    def test_body_is_pretty_printed(self, client: TestClient, plan):
        """Response text should contain newlines (pretty-printed JSON)."""
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        assert "\n" in resp.text

    def test_plan_id_matches_filename(self, client: TestClient, plan):
        resp = client.get(f"/travel-plans/{plan['id']}/export")
        cd = resp.headers.get("content-disposition", "")
        assert str(plan["id"]) in cd

    def test_different_plans_different_filenames(self, client: TestClient, plan):
        plan2 = client.post("/travel-plans", json={
            "destination": "Paris",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "budget": 1500.0,
        }).json()

        cd1 = client.get(f"/travel-plans/{plan['id']}/export").headers.get("content-disposition", "")
        cd2 = client.get(f"/travel-plans/{plan2['id']}/export").headers.get("content-disposition", "")
        assert cd1 != cd2
