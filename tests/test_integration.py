"""Integration tests for advanced features (Task #16).

These tests cover multi-step, cross-feature workflows rather than isolated units:
  - Full travel planning lifecycle (create → update → expenses → budget summary)
  - Expense isolation between plans
  - Calendar export pipeline (plan with itinerary → export)
  - AI plan generation → expense tracking
  - Search endpoints (places, hotels, flights) error propagation
  - Concurrent plan management
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import httpx

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TOKYO_PLAN = {
    "destination": "Tokyo",
    "start_date": "2026-07-01",
    "end_date": "2026-07-05",
    "budget": 3000.0,
    "interests": "food,culture",
    "status": "draft",
}

PARIS_PLAN = {
    "destination": "Paris",
    "start_date": "2026-08-10",
    "end_date": "2026-08-15",
    "budget": 5000.0,
    "interests": "art,food",
    "status": "draft",
}


def _create_plan(client, payload=None):
    r = client.post("/travel-plans", json=payload or TOKYO_PLAN)
    assert r.status_code == 201
    return r.json()


def _add_expense(client, plan_id, name, amount, category, day_offset=0):
    base = date(2026, 7, 1) + timedelta(days=day_offset)
    r = client.post(f"/plans/{plan_id}/expenses", json={
        "name": name,
        "amount": amount,
        "category": category,
        "date": str(base),
        "notes": "",
    })
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# 1. Full Travel Plan Lifecycle
# ---------------------------------------------------------------------------

class TestTravelPlanLifecycle:
    """Create plan → update → confirm → delete workflow."""

    def test_create_and_retrieve_plan(self, client):
        plan = _create_plan(client)
        r = client.get(f"/travel-plans/{plan['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["destination"] == "Tokyo"
        assert data["status"] == "draft"
        assert data["budget"] == 3000.0

    def test_update_plan_destination_and_budget(self, client):
        plan = _create_plan(client)
        r = client.patch(f"/travel-plans/{plan['id']}", json={
            "destination": "Kyoto",
            "budget": 2500.0,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["destination"] == "Kyoto"
        assert data["budget"] == 2500.0
        assert data["interests"] == "food,culture"  # unchanged

    def test_confirm_draft_plan(self, client):
        plan = _create_plan(client)
        r = client.patch(f"/travel-plans/{plan['id']}", json={"status": "confirmed"})
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"

    def test_plan_appears_in_list(self, client):
        plan_a = _create_plan(client, TOKYO_PLAN)
        plan_b = _create_plan(client, PARIS_PLAN)
        r = client.get("/travel-plans")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()["items"]]
        assert plan_a["id"] in ids
        assert plan_b["id"] in ids

    def test_delete_plan_removes_it(self, client):
        plan = _create_plan(client)
        plan_id = plan["id"]
        r = client.delete(f"/travel-plans/{plan_id}")
        assert r.status_code == 204
        r = client.get(f"/travel-plans/{plan_id}")
        assert r.status_code == 404

    def test_update_nonexistent_plan_returns_404(self, client):
        r = client.patch("/travel-plans/99999", json={"destination": "Nowhere"})
        assert r.status_code == 404

    def test_delete_nonexistent_plan_returns_404(self, client):
        r = client.delete("/travel-plans/99999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2. Expense Tracking Integration
# ---------------------------------------------------------------------------

class TestExpenseLifecycle:
    """Full expense CRUD workflow against a real plan."""

    def test_add_expense_and_retrieve(self, client):
        plan = _create_plan(client)
        expense = _add_expense(client, plan["id"], "Sushi dinner", 45.0, "food")
        assert expense["name"] == "Sushi dinner"
        assert expense["amount"] == 45.0
        assert expense["travel_plan_id"] == plan["id"]

        r = client.get(f"/plans/{plan['id']}/expenses/{expense['id']}")
        assert r.status_code == 200
        assert r.json()["name"] == "Sushi dinner"

    def test_update_expense_amount(self, client):
        plan = _create_plan(client)
        expense = _add_expense(client, plan["id"], "Train pass", 30.0, "transport")
        r = client.patch(f"/plans/{plan['id']}/expenses/{expense['id']}", json={"amount": 35.0})
        assert r.status_code == 200
        assert r.json()["amount"] == 35.0

    def test_delete_expense(self, client):
        plan = _create_plan(client)
        expense = _add_expense(client, plan["id"], "Museum ticket", 12.0, "sightseeing")
        r = client.delete(f"/plans/{plan['id']}/expenses/{expense['id']}")
        assert r.status_code == 204
        r = client.get(f"/plans/{plan['id']}/expenses/{expense['id']}")
        assert r.status_code == 404

    def test_expense_on_nonexistent_plan_returns_404(self, client):
        r = client.post("/plans/99999/expenses", json={
            "name": "Ghost expense",
            "amount": 10.0,
            "category": "misc",
            "date": "2026-07-01",
        })
        assert r.status_code == 404

    def test_expense_cross_plan_isolation(self, client):
        """Expense belonging to plan A is not accessible via plan B's endpoints."""
        plan_a = _create_plan(client, TOKYO_PLAN)
        plan_b = _create_plan(client, PARIS_PLAN)
        expense = _add_expense(client, plan_a["id"], "Ramen", 12.0, "food")

        r = client.get(f"/plans/{plan_b['id']}/expenses/{expense['id']}")
        assert r.status_code == 404

    def test_list_expenses_scoped_to_plan(self, client):
        plan_a = _create_plan(client, TOKYO_PLAN)
        plan_b = _create_plan(client, PARIS_PLAN)
        _add_expense(client, plan_a["id"], "Tokyo expense", 20.0, "food")
        _add_expense(client, plan_b["id"], "Paris expense", 50.0, "food")

        r_a = client.get(f"/plans/{plan_a['id']}/expenses")
        r_b = client.get(f"/plans/{plan_b['id']}/expenses")
        assert len(r_a.json()) == 1
        assert len(r_b.json()) == 1
        assert r_a.json()[0]["name"] == "Tokyo expense"
        assert r_b.json()[0]["name"] == "Paris expense"


# ---------------------------------------------------------------------------
# 3. Budget Summary Integration
# ---------------------------------------------------------------------------

class TestBudgetSummaryIntegration:
    """Plan creation → multiple expenses → verify aggregate budget summary."""

    def test_empty_budget_summary(self, client):
        plan = _create_plan(client)
        r = client.get(f"/plans/{plan['id']}/expenses/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["budget"] == 3000.0
        assert data["total_spent"] == 0.0
        assert data["remaining"] == 3000.0
        assert data["expense_count"] == 0
        assert data["by_category"] == {}

    def test_budget_summary_after_expenses(self, client):
        plan = _create_plan(client)
        pid = plan["id"]
        _add_expense(client, pid, "Ramen", 15.0, "food", day_offset=0)
        _add_expense(client, pid, "Sushi", 40.0, "food", day_offset=1)
        _add_expense(client, pid, "Train", 25.0, "transport", day_offset=2)

        r = client.get(f"/plans/{pid}/expenses/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["total_spent"] == 80.0
        assert data["remaining"] == 2920.0
        assert data["expense_count"] == 3
        assert data["by_category"]["food"] == 55.0
        assert data["by_category"]["transport"] == 25.0

    def test_budget_summary_reflects_deletion(self, client):
        plan = _create_plan(client)
        pid = plan["id"]
        e1 = _add_expense(client, pid, "Hotel", 200.0, "accommodation")
        _add_expense(client, pid, "Dinner", 50.0, "food")

        # Delete hotel expense
        client.delete(f"/plans/{pid}/expenses/{e1['id']}")

        r = client.get(f"/plans/{pid}/expenses/summary")
        data = r.json()
        assert data["total_spent"] == 50.0
        assert data["expense_count"] == 1
        assert "accommodation" not in data["by_category"]

    def test_budget_summary_reflects_update(self, client):
        plan = _create_plan(client)
        pid = plan["id"]
        expense = _add_expense(client, pid, "Bus", 10.0, "transport")
        client.patch(f"/plans/{pid}/expenses/{expense['id']}", json={"amount": 20.0})

        r = client.get(f"/plans/{pid}/expenses/summary")
        data = r.json()
        assert data["total_spent"] == 20.0
        assert data["by_category"]["transport"] == 20.0

    def test_budget_summary_plan_not_found(self, client):
        r = client.get("/plans/99999/expenses/summary")
        assert r.status_code == 404

    def test_over_budget_shown_as_negative_remaining(self, client):
        plan = _create_plan(client)
        pid = plan["id"]
        _add_expense(client, pid, "Luxury hotel", 4000.0, "accommodation")
        r = client.get(f"/plans/{pid}/expenses/summary")
        data = r.json()
        assert data["remaining"] < 0


# ---------------------------------------------------------------------------
# 4. AI Plan Generation Integration
# ---------------------------------------------------------------------------

class TestAIPlanGenerationIntegration:
    """Mocked Gemini — tests that AI-generated plans are persisted correctly
    and that expenses can be tracked against AI-generated plans."""

    def _make_ai_result(self):
        from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
        return AIItineraryResult(
            destination="Tokyo",
            summary="3-day Tokyo itinerary",
            days=[
                AIDayItinerary(
                    date="2026-07-01",
                    notes="Explore Asakusa",
                    transport="Subway",
                    places=[
                        AIPlace(
                            name="Senso-ji Temple",
                            category="sightseeing",
                            address="2-3-1 Asakusa",
                            estimated_cost=0.0,
                            ai_reason="Iconic historic temple",
                        ),
                        AIPlace(
                            name="Nakamise Shopping Street",
                            category="shopping",
                            address="Asakusa, Tokyo",
                            estimated_cost=30.0,
                            ai_reason="Traditional souvenirs",
                        ),
                    ],
                ),
                AIDayItinerary(
                    date="2026-07-02",
                    notes="Shibuya and Harajuku",
                    transport="Walk",
                    places=[
                        AIPlace(
                            name="Shibuya Crossing",
                            category="sightseeing",
                            address="Shibuya, Tokyo",
                            estimated_cost=0.0,
                            ai_reason="Famous scramble crossing",
                        ),
                    ],
                ),
            ],
        )

    def test_ai_generate_creates_plan_with_itineraries(self, client):
        ai_result = self._make_ai_result()
        with patch("app.routers.ai_plans.GeminiService") as MockService:
            MockService.return_value.generate_itinerary.return_value = ai_result
            r = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "budget": 1500.0,
                "interests": "culture",
                "status": "draft",
            })
        assert r.status_code == 201
        data = r.json()
        assert data["destination"] == "Tokyo"
        assert len(data["itineraries"]) == 2
        day1 = data["itineraries"][0]
        assert len(day1["places"]) == 2
        assert day1["places"][0]["name"] == "Senso-ji Temple"

    def test_ai_generate_plan_supports_expense_tracking(self, client):
        ai_result = self._make_ai_result()
        with patch("app.routers.ai_plans.GeminiService") as MockService:
            MockService.return_value.generate_itinerary.return_value = ai_result
            r = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "budget": 1500.0,
                "interests": "culture",
                "status": "draft",
            })
        plan_id = r.json()["id"]

        # Add an expense to the AI-generated plan
        _add_expense(client, plan_id, "Street food", 8.0, "food")
        summary = client.get(f"/plans/{plan_id}/expenses/summary").json()
        assert summary["total_spent"] == 8.0
        assert summary["budget"] == 1500.0

    def test_ai_generate_503_when_no_api_key(self, client):
        with patch("app.routers.ai_plans.GeminiService") as MockService:
            MockService.return_value.generate_itinerary.side_effect = ValueError("GEMINI_API_KEY not set")
            r = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "budget": 1000.0,
                "interests": "food",
                "status": "draft",
            })
        assert r.status_code == 503

    def test_ai_preview_does_not_persist(self, client):
        ai_result = self._make_ai_result()
        with patch("app.routers.ai_plans.GeminiService") as MockService:
            MockService.return_value.generate_itinerary.return_value = ai_result
            r = client.post("/ai/preview", json={
                "destination": "Tokyo",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "budget": 1000.0,
                "interests": "food",
                "status": "draft",
            })
        assert r.status_code == 200
        # The plan list should be empty — preview does not persist
        plans = client.get("/travel-plans").json()["items"]
        assert len(plans) == 0


# ---------------------------------------------------------------------------
# 5. Calendar Export Integration
# ---------------------------------------------------------------------------

class TestCalendarExportIntegration:
    """Tests the full calendar export flow for a persisted plan with itineraries."""

    def _seed_plan_with_itinerary(self, client):
        """Generate an AI plan with real itinerary rows, then return the plan id."""
        from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
        ai_result = AIItineraryResult(
            destination="Kyoto",
            summary="Kyoto day trip",
            days=[
                AIDayItinerary(
                    date="2026-09-01",
                    notes="Temples",
                    transport="Bus",
                    places=[
                        AIPlace(
                            name="Kinkaku-ji",
                            category="sightseeing",
                            address="Kinkakuji-cho, Kita, Kyoto",
                            estimated_cost=5.0,
                            ai_reason="Golden Pavilion",
                        ),
                    ],
                ),
            ],
        )
        with patch("app.routers.ai_plans.GeminiService") as MockService:
            MockService.return_value.generate_itinerary.return_value = ai_result
            r = client.post("/ai/generate", json={
                "destination": "Kyoto",
                "start_date": "2026-09-01",
                "end_date": "2026-09-01",
                "budget": 500.0,
                "interests": "sightseeing",
                "status": "draft",
            })
        assert r.status_code == 201
        return r.json()["id"]

    def test_calendar_export_success(self, client):
        plan_id = self._seed_plan_with_itinerary(client)
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "id": "evt123",
            "htmlLink": "https://calendar.google.com/event?eid=evt123",
            "summary": "Kyoto — Sep 1",
        }
        with patch("app.calendar_service.httpx.Client") as MockHTTP:
            instance = MockHTTP.return_value.__enter__.return_value
            instance.post.return_value = fake_response
            r = client.post(f"/plans/{plan_id}/calendar/export", json={
                "access_token": "fake-token-abc"
            })
        assert r.status_code == 200
        data = r.json()
        assert data["events_created"] == 1
        assert len(data["events"]) == 1

    def test_calendar_export_404_no_plan(self, client):
        r = client.post("/plans/99999/calendar/export", json={"access_token": "tok"})
        assert r.status_code == 404

    def test_calendar_export_422_no_itinerary(self, client):
        """Plan without itinerary days should return 422."""
        plan = _create_plan(client, TOKYO_PLAN)
        r = client.post(f"/plans/{plan['id']}/calendar/export", json={"access_token": "tok"})
        assert r.status_code == 422

    def test_calendar_export_401_invalid_token(self, client):
        plan_id = self._seed_plan_with_itinerary(client)
        with patch("app.calendar_service.httpx.Client") as MockHTTP:
            instance = MockHTTP.return_value.__enter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            instance.post.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=mock_resp
            )
            r = client.post(f"/plans/{plan_id}/calendar/export", json={"access_token": "bad-token"})
        assert r.status_code == 401

    def test_calendar_export_502_on_google_error(self, client):
        plan_id = self._seed_plan_with_itinerary(client)
        with patch("app.calendar_service.httpx.Client") as MockHTTP:
            instance = MockHTTP.return_value.__enter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            instance.post.side_effect = httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_resp
            )
            r = client.post(f"/plans/{plan_id}/calendar/export", json={"access_token": "tok"})
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# 6. Search Endpoints Error Propagation
# ---------------------------------------------------------------------------

class TestSearchIntegration:
    """Verify search endpoints handle service errors correctly."""

    def test_places_search_503_without_api_key(self, client):
        with patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.side_effect = ValueError("API key missing")
            r = client.get("/search/places", params={"destination": "Tokyo"})
        assert r.status_code == 503

    def test_hotels_search_503_without_api_key(self, client):
        with patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.side_effect = ValueError("API key missing")
            r = client.get("/search/hotels", params={"destination": "Paris"})
        assert r.status_code == 503

    def test_flights_search_503_without_api_key(self, client):
        with patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.side_effect = ValueError("API key missing")
            r = client.get("/search/flights", params={
                "departure_city": "NYC", "arrival_city": "Tokyo"
            })
        assert r.status_code == 503

    def test_places_search_502_on_upstream_failure(self, client):
        with patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.side_effect = RuntimeError("upstream down")
            r = client.get("/search/places", params={"destination": "Tokyo"})
        assert r.status_code == 502

    def test_hotels_search_502_on_upstream_failure(self, client):
        with patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.side_effect = RuntimeError("upstream down")
            r = client.get("/search/hotels", params={"destination": "Rome"})
        assert r.status_code == 502

    def test_flights_search_502_on_upstream_failure(self, client):
        with patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.side_effect = RuntimeError("upstream down")
            r = client.get("/search/flights", params={
                "departure_city": "LAX", "arrival_city": "LHR"
            })
        assert r.status_code == 502

    def test_places_search_missing_destination_param(self, client):
        r = client.get("/search/places")
        assert r.status_code == 422

    def test_flights_search_missing_arrival_city(self, client):
        r = client.get("/search/flights", params={"departure_city": "NYC"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 7. Multi-Plan Concurrent Management
# ---------------------------------------------------------------------------

class TestMultiPlanManagement:
    """Multiple plans co-exist and don't interfere with each other."""

    def test_multiple_plans_independent_budgets(self, client):
        p1 = _create_plan(client, TOKYO_PLAN)
        p2 = _create_plan(client, PARIS_PLAN)

        _add_expense(client, p1["id"], "Sake", 20.0, "food")
        _add_expense(client, p1["id"], "Train", 10.0, "transport")
        _add_expense(client, p2["id"], "Wine", 60.0, "food")

        s1 = client.get(f"/plans/{p1['id']}/expenses/summary").json()
        s2 = client.get(f"/plans/{p2['id']}/expenses/summary").json()

        assert s1["total_spent"] == 30.0
        assert s1["budget"] == 3000.0
        assert s2["total_spent"] == 60.0
        assert s2["budget"] == 5000.0

    def test_delete_plan_does_not_affect_other_plan(self, client):
        p1 = _create_plan(client, TOKYO_PLAN)
        p2 = _create_plan(client, PARIS_PLAN)
        _add_expense(client, p2["id"], "Louvre", 25.0, "sightseeing")

        client.delete(f"/travel-plans/{p1['id']}")

        r = client.get(f"/plans/{p2['id']}/expenses/summary")
        assert r.status_code == 200
        assert r.json()["total_spent"] == 25.0

    def test_updating_one_plan_does_not_affect_another(self, client):
        p1 = _create_plan(client, TOKYO_PLAN)
        p2 = _create_plan(client, PARIS_PLAN)

        client.patch(f"/travel-plans/{p1['id']}", json={"budget": 100.0})

        r2 = client.get(f"/travel-plans/{p2['id']}")
        assert r2.json()["budget"] == 5000.0
