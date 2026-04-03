"""Tests for AI plan refinement endpoint.

Endpoint covered:
  POST /travel-plans/{id}/refine  → refine itinerary via AI instruction (200)
"""

from unittest.mock import MagicMock, patch

from app.ai import AIItineraryResult

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Paris",
    "start_date": "2026-06-01",
    "end_date": "2026-06-03",
    "budget": 2000.0,
    "interests": "art,food",
}

REFINED_AI_RESPONSE = {
    "days": [
        {
            "date": "2026-06-01",
            "notes": "Museum day",
            "transport": "metro",
            "places": [
                {
                    "name": "Louvre Museum",
                    "category": "museum",
                    "address": "Rue de Rivoli, Paris",
                    "estimated_cost": 20.0,
                    "ai_reason": "World-class art museum",
                },
                {
                    "name": "Cafe de Flore",
                    "category": "cafe",
                    "address": "172 Bd Saint-Germain, Paris",
                    "estimated_cost": 15.0,
                    "ai_reason": "Iconic Parisian cafe",
                },
            ],
        },
        {
            "date": "2026-06-02",
            "notes": "Landmarks day",
            "transport": "walking",
            "places": [
                {
                    "name": "Eiffel Tower",
                    "category": "landmark",
                    "address": "Champ de Mars, Paris",
                    "estimated_cost": 25.0,
                    "ai_reason": "Iconic Parisian landmark",
                },
            ],
        },
        {
            "date": "2026-06-03",
            "notes": "Final day",
            "transport": "bus",
            "places": [
                {
                    "name": "Palace of Versailles",
                    "category": "historic",
                    "address": "Place d'Armes, Versailles",
                    "estimated_cost": 20.0,
                    "ai_reason": "Royal palace near Paris",
                },
            ],
        },
    ],
    "total_estimated_cost": 80.0,
}

ORIGINAL_AI_RESPONSE = {
    "days": [
        {
            "date": "2026-06-01",
            "notes": "Day 1",
            "transport": "taxi",
            "places": [
                {
                    "name": "Notre Dame",
                    "category": "landmark",
                    "address": "6 Parvis Notre-Dame, Paris",
                    "estimated_cost": 0.0,
                    "ai_reason": "Gothic cathedral",
                },
            ],
        },
        {
            "date": "2026-06-02",
            "notes": "Day 2",
            "transport": "metro",
            "places": [],
        },
        {
            "date": "2026-06-03",
            "notes": "Day 3",
            "transport": "walking",
            "places": [],
        },
    ],
    "total_estimated_cost": 0.0,
}


def create_plan(client, **overrides):
    payload = {**PLAN_PAYLOAD, **overrides}
    resp = client.post("/travel-plans", json=payload)
    assert resp.status_code == 201
    return resp.json()


def create_plan_with_itineraries(client):
    """Create a plan, then generate itineraries via mocked AI."""
    with patch("app.routers.ai_plans.GeminiService") as MockSvc:
        mock_svc = MagicMock()
        mock_svc.generate_itinerary.return_value = AIItineraryResult.model_validate(
            ORIGINAL_AI_RESPONSE
        )
        MockSvc.return_value = mock_svc
        resp = client.post("/ai/generate", json=PLAN_PAYLOAD)
        assert resp.status_code == 201
        return resp.json()


def _patched_refine_service(refined_response=None):
    """Returns a context manager that patches GeminiService used in travel_plans router."""
    mock_svc = MagicMock()
    mock_svc.refine_itinerary.return_value = AIItineraryResult.model_validate(
        refined_response or REFINED_AI_RESPONSE
    )
    return patch("app.routers.travel_plans.GeminiService", return_value=mock_svc)


# ===========================================================================
# POST /travel-plans/{id}/refine  — status codes
# ===========================================================================

class TestRefineStatusCodes:
    def test_returns_200(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add more restaurants"},
            )
        assert resp.status_code == 200

    def test_404_when_plan_not_found(self, client):
        with _patched_refine_service():
            resp = client.post(
                "/travel-plans/9999/refine",
                json={"instruction": "Add more restaurants"},
            )
        assert resp.status_code == 404

    def test_404_detail_message(self, client):
        with _patched_refine_service():
            resp = client.post(
                "/travel-plans/9999/refine",
                json={"instruction": "Add more restaurants"},
            )
        assert "not found" in resp.json()["detail"].lower()

    def test_503_when_no_api_key(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            MockSvc.return_value.refine_itinerary.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add restaurants"},
            )
        assert resp.status_code == 503

    def test_502_when_ai_fails(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            MockSvc.return_value.refine_itinerary.side_effect = RuntimeError(
                "Gemini API error"
            )
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add restaurants"},
            )
        assert resp.status_code == 502

    def test_422_when_instruction_missing(self, client):
        plan = create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/refine", json={})
        assert resp.status_code == 422

    def test_422_when_instruction_empty_string(self, client):
        plan = create_plan(client)
        resp = client.post(
            f"/travel-plans/{plan['id']}/refine",
            json={"instruction": ""},
        )
        assert resp.status_code == 422

    def test_422_when_instruction_too_long(self, client):
        plan = create_plan(client)
        resp = client.post(
            f"/travel-plans/{plan['id']}/refine",
            json={"instruction": "x" * 2001},
        )
        assert resp.status_code == 422

    def test_accepts_instruction_at_max_length(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "x" * 2000},
            )
        assert resp.status_code == 200


# ===========================================================================
# POST /travel-plans/{id}/refine  — response content
# ===========================================================================

class TestRefineResponseContent:
    def test_response_has_id(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add more art museums"},
            )
        assert resp.json()["id"] == plan["id"]

    def test_response_destination_unchanged(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add more art museums"},
            )
        assert resp.json()["destination"] == "Paris"

    def test_response_budget_unchanged(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Focus on cheaper options"},
            )
        assert resp.json()["budget"] == 2000.0

    def test_response_has_itineraries(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add more restaurants"},
            )
        assert len(resp.json()["itineraries"]) == 3

    def test_refined_place_names(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add Louvre"},
            )
        day1_places = resp.json()["itineraries"][0]["places"]
        names = [p["name"] for p in day1_places]
        assert "Louvre Museum" in names

    def test_refined_place_count_day1(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add cafe"},
            )
        assert len(resp.json()["itineraries"][0]["places"]) == 2

    def test_refined_day_notes(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Restructure days"},
            )
        assert resp.json()["itineraries"][0]["notes"] == "Museum day"

    def test_refined_day_transport(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Use metro more"},
            )
        assert resp.json()["itineraries"][0]["transport"] == "metro"

    def test_response_has_expenses(self, client):
        plan = create_plan(client)
        # Add an expense before refining
        client.post(
            f"/plans/{plan['id']}/expenses",
            json={"name": "Hotel", "amount": 150.0, "category": "lodging"},
        )
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "More cultural activities"},
            )
        # expenses should NOT be deleted by refinement
        assert len(resp.json()["expenses"]) == 1

    def test_expense_preserved_after_refine(self, client):
        plan = create_plan(client)
        client.post(
            f"/plans/{plan['id']}/expenses",
            json={"name": "Dinner", "amount": 60.0, "category": "food"},
        )
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add more museums"},
            )
        assert resp.json()["expenses"][0]["name"] == "Dinner"


# ===========================================================================
# POST /travel-plans/{id}/refine  — itinerary replacement
# ===========================================================================

class TestRefineItineraryReplacement:
    def test_old_itineraries_replaced(self, client):
        """Original itinerary places should no longer exist after refinement."""
        plan = create_plan_with_itineraries(client)
        original_place = plan["itineraries"][0]["places"][0]["name"]
        assert original_place == "Notre Dame"

        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Replace all places with museums"},
            )
        new_names = [
            p["name"]
            for day in resp.json()["itineraries"]
            for p in day["places"]
        ]
        assert "Notre Dame" not in new_names

    def test_new_places_created(self, client):
        plan = create_plan_with_itineraries(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add Eiffel Tower"},
            )
        all_names = [
            p["name"]
            for day in resp.json()["itineraries"]
            for p in day["places"]
        ]
        assert "Eiffel Tower" in all_names

    def test_refine_blank_plan_no_itineraries(self, client):
        """Refining a plan with no existing itineraries should still work."""
        plan = create_plan(client)
        assert plan["itineraries"] == []
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Build a full itinerary from scratch"},
            )
        assert resp.status_code == 200
        assert len(resp.json()["itineraries"]) == 3

    def test_place_order_is_sequential(self, client):
        plan = create_plan(client)
        with _patched_refine_service():
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Add multiple places"},
            )
        day1_places = resp.json()["itineraries"][0]["places"]
        orders = [p["order"] for p in day1_places]
        assert orders == list(range(len(orders)))


# ===========================================================================
# POST /travel-plans/{id}/refine  — service call verification
# ===========================================================================

class TestRefineServiceCall:
    def test_instruction_passed_to_service(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            mock_svc = MagicMock()
            mock_svc.refine_itinerary.return_value = AIItineraryResult.model_validate(
                REFINED_AI_RESPONSE
            )
            MockSvc.return_value = mock_svc
            client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Focus on museums"},
            )
        call_kwargs = mock_svc.refine_itinerary.call_args.kwargs
        assert call_kwargs["instruction"] == "Focus on museums"

    def test_destination_passed_to_service(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            mock_svc = MagicMock()
            mock_svc.refine_itinerary.return_value = AIItineraryResult.model_validate(
                REFINED_AI_RESPONSE
            )
            MockSvc.return_value = mock_svc
            client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "More museums"},
            )
        call_kwargs = mock_svc.refine_itinerary.call_args.kwargs
        assert call_kwargs["destination"] == "Paris"

    def test_budget_passed_to_service(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            mock_svc = MagicMock()
            mock_svc.refine_itinerary.return_value = AIItineraryResult.model_validate(
                REFINED_AI_RESPONSE
            )
            MockSvc.return_value = mock_svc
            client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Reduce costs"},
            )
        call_kwargs = mock_svc.refine_itinerary.call_args.kwargs
        assert call_kwargs["budget"] == 2000.0

    def test_current_days_passed_to_service(self, client):
        """Service receives current_days list (even if empty)."""
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            mock_svc = MagicMock()
            mock_svc.refine_itinerary.return_value = AIItineraryResult.model_validate(
                REFINED_AI_RESPONSE
            )
            MockSvc.return_value = mock_svc
            client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Update"},
            )
        call_kwargs = mock_svc.refine_itinerary.call_args.kwargs
        assert "current_days" in call_kwargs
        assert isinstance(call_kwargs["current_days"], list)

    def test_current_days_includes_existing_places(self, client):
        plan = create_plan_with_itineraries(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            mock_svc = MagicMock()
            mock_svc.refine_itinerary.return_value = AIItineraryResult.model_validate(
                REFINED_AI_RESPONSE
            )
            MockSvc.return_value = mock_svc
            client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Improve"},
            )
        call_kwargs = mock_svc.refine_itinerary.call_args.kwargs
        current_days = call_kwargs["current_days"]
        # Original had "Notre Dame" in day 1
        assert any(
            any(p["name"] == "Notre Dame" for p in day.get("places", []))
            for day in current_days
        )

    def test_503_detail_contains_key_error(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            MockSvc.return_value.refine_itinerary.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Update"},
            )
        assert "GEMINI_API_KEY" in resp.json()["detail"]

    def test_502_detail_contains_error_message(self, client):
        plan = create_plan(client)
        with patch("app.routers.travel_plans.GeminiService") as MockSvc:
            MockSvc.return_value.refine_itinerary.side_effect = RuntimeError(
                "network timeout"
            )
            resp = client.post(
                f"/travel-plans/{plan['id']}/refine",
                json={"instruction": "Update"},
            )
        assert "refinement failed" in resp.json()["detail"].lower()
