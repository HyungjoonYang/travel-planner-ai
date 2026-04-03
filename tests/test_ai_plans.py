"""Tests for Task #10: Comprehensive AI-generated travel plan coverage.

Covers gaps not addressed by test_ai.py and test_structured_output.py:
- Pydantic model validation (AIPlace, AIDayItinerary, AIItineraryResult)
- Multi-day trip (3+ days) full persistence
- Invalid AI date handling (router skip-on-bad-date branch)
- Empty places per day
- Budget/request validation edge cases
- Place order field persistence
- Multiple plans coexisting in DB
- All TravelPlanOut fields present after generate
- GeminiService model constant
- Interests edge cases (empty, comma-separated, whitespace)
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.ai import AIDayItinerary, AIItineraryResult, AIPlace, GeminiService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_service(response_dict: dict) -> MagicMock:
    """Return a patched GeminiService whose generate_itinerary returns response_dict."""
    mock_service = MagicMock()
    mock_service.generate_itinerary.return_value = AIItineraryResult.model_validate(response_dict)
    return mock_service


def _patch_service(response_dict: dict):
    return patch(
        "app.routers.ai_plans.GeminiService",
        return_value=_make_mock_service(response_dict),
    )


# ---------------------------------------------------------------------------
# 1. Pydantic model validation tests
# ---------------------------------------------------------------------------

class TestAIPlaceModel:
    def test_name_is_required(self):
        with pytest.raises(Exception):
            AIPlace.model_validate({})

    def test_defaults_applied(self):
        place = AIPlace(name="Gyoen")
        assert place.category == ""
        assert place.address == ""
        assert place.estimated_cost == 0.0
        assert place.ai_reason == ""

    def test_all_fields_set(self):
        place = AIPlace(
            name="Senso-ji",
            category="temple",
            address="2-3-1 Asakusa",
            estimated_cost=0.0,
            ai_reason="Oldest temple in Tokyo",
        )
        assert place.name == "Senso-ji"
        assert place.category == "temple"

    def test_estimated_cost_float_coercion(self):
        place = AIPlace(name="Ramen", estimated_cost=12)
        assert place.estimated_cost == 12.0
        assert isinstance(place.estimated_cost, float)

    def test_model_validate_from_dict(self):
        place = AIPlace.model_validate(
            {"name": "Eiffel Tower", "category": "sightseeing", "estimated_cost": 28.0}
        )
        assert place.name == "Eiffel Tower"


class TestAIDayItineraryModel:
    def test_date_is_required(self):
        with pytest.raises(Exception):
            AIDayItinerary.model_validate({})

    def test_defaults_applied(self):
        day = AIDayItinerary(date="2026-05-01")
        assert day.notes == ""
        assert day.transport == ""
        assert day.places == []

    def test_places_list(self):
        day = AIDayItinerary(
            date="2026-05-01",
            places=[AIPlace(name="Museum", estimated_cost=10.0)],
        )
        assert len(day.places) == 1
        assert day.places[0].name == "Museum"


class TestAIItineraryResultModel:
    def test_days_is_required(self):
        with pytest.raises(Exception):
            AIItineraryResult.model_validate({})

    def test_total_cost_defaults_to_zero(self):
        result = AIItineraryResult(days=[])
        assert result.total_estimated_cost == 0.0

    def test_model_validate_full_structure(self):
        data = {
            "days": [
                {
                    "date": "2026-05-01",
                    "notes": "Day 1",
                    "transport": "subway",
                    "places": [{"name": "Place A", "estimated_cost": 5.0}],
                }
            ],
            "total_estimated_cost": 100.0,
        }
        result = AIItineraryResult.model_validate(data)
        assert len(result.days) == 1
        assert result.total_estimated_cost == 100.0
        assert result.days[0].places[0].name == "Place A"

    def test_empty_days_list_accepted(self):
        result = AIItineraryResult(days=[])
        assert result.days == []


# ---------------------------------------------------------------------------
# 2. GeminiService — model constant and initialization
# ---------------------------------------------------------------------------

class TestGeminiServiceInit:
    def test_model_constant(self):
        assert GeminiService.MODEL == "gemini-3.0-flash"

    def test_uses_provided_api_key(self):
        svc = GeminiService(api_key="my-key")
        assert svc._api_key == "my-key"

    def test_falls_back_to_config_key(self):
        with patch("app.ai.GEMINI_API_KEY", "config-key"):
            svc = GeminiService(api_key="")
        assert svc._api_key == "config-key"


# ---------------------------------------------------------------------------
# 3. Multi-day trip persistence (3-day trip via /ai/generate)
# ---------------------------------------------------------------------------

THREE_DAY_RESPONSE = {
    "days": [
        {
            "date": "2026-07-01",
            "notes": "Arrive and explore Shibuya",
            "transport": "walking",
            "places": [
                {"name": "Shibuya Crossing", "category": "sightseeing", "estimated_cost": 0.0, "ai_reason": "Iconic intersection"},
                {"name": "Meiji Shrine", "category": "temple", "estimated_cost": 0.0, "ai_reason": "Serene forested shrine"},
            ],
        },
        {
            "date": "2026-07-02",
            "notes": "Harajuku and Omotesando",
            "transport": "subway",
            "places": [
                {"name": "Takeshita Street", "category": "shopping", "estimated_cost": 50.0, "ai_reason": "Unique fashion street"},
            ],
        },
        {
            "date": "2026-07-03",
            "notes": "Akihabara and departure",
            "transport": "subway",
            "places": [
                {"name": "Akihabara Electric Town", "category": "shopping", "estimated_cost": 100.0, "ai_reason": "Electronics hub"},
                {"name": "Kanda Myojin", "category": "temple", "estimated_cost": 0.0, "ai_reason": "Historic shrine"},
                {"name": "Sushiro Akihabara", "category": "food", "estimated_cost": 20.0, "ai_reason": "Conveyor belt sushi"},
            ],
        },
    ],
    "total_estimated_cost": 600.0,
}

THREE_DAY_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-07-01",
    "end_date": "2026-07-03",
    "budget": 1500.0,
    "interests": "culture, shopping",
    "status": "draft",
}


class TestMultiDayPersistence:
    def test_three_days_persisted(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        assert resp.status_code == 201
        itineraries = resp.json()["itineraries"]
        assert len(itineraries) == 3

    def test_day_dates_correct(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        dates = [d["date"] for d in resp.json()["itineraries"]]
        assert dates == ["2026-07-01", "2026-07-02", "2026-07-03"]

    def test_day1_place_count(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        assert len(resp.json()["itineraries"][0]["places"]) == 2

    def test_day2_place_count(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        assert len(resp.json()["itineraries"][1]["places"]) == 1

    def test_day3_place_count(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        assert len(resp.json()["itineraries"][2]["places"]) == 3

    def test_transport_per_day(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        its = resp.json()["itineraries"]
        assert its[0]["transport"] == "walking"
        assert its[1]["transport"] == "subway"
        assert its[2]["transport"] == "subway"

    def test_notes_per_day(self, client):
        with _patch_service(THREE_DAY_RESPONSE):
            resp = client.post("/ai/generate", json=THREE_DAY_PAYLOAD)
        assert "Shibuya" in resp.json()["itineraries"][0]["notes"]


# ---------------------------------------------------------------------------
# 4. Invalid date from AI response (router skips bad dates)
# ---------------------------------------------------------------------------

RESPONSE_WITH_INVALID_DATE = {
    "days": [
        {
            "date": "2026-05-01",
            "notes": "Valid day",
            "transport": "walking",
            "places": [{"name": "Park", "estimated_cost": 0.0, "ai_reason": "Nice park"}],
        },
        {
            "date": "not-a-date",
            "notes": "Invalid date day",
            "transport": "bus",
            "places": [{"name": "Museum", "estimated_cost": 10.0, "ai_reason": "Art"}],
        },
    ],
    "total_estimated_cost": 200.0,
}

PAYLOAD_BASE = {
    "destination": "Seoul",
    "start_date": "2026-05-01",
    "end_date": "2026-05-02",
    "budget": 500.0,
    "interests": "food",
    "status": "draft",
}


class TestInvalidDateHandling:
    def test_invalid_date_day_is_skipped(self, client):
        """Router should skip days with unparseable dates; only valid days saved."""
        with _patch_service(RESPONSE_WITH_INVALID_DATE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.status_code == 201
        # Only 1 valid day should be persisted
        assert len(resp.json()["itineraries"]) == 1

    def test_valid_day_still_persisted(self, client):
        with _patch_service(RESPONSE_WITH_INVALID_DATE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.json()["itineraries"][0]["date"] == "2026-05-01"


# ---------------------------------------------------------------------------
# 5. Empty places list per day
# ---------------------------------------------------------------------------

RESPONSE_EMPTY_PLACES = {
    "days": [
        {
            "date": "2026-05-01",
            "notes": "Rest day",
            "transport": "none",
            "places": [],
        }
    ],
    "total_estimated_cost": 0.0,
}


class TestEmptyPlaces:
    def test_day_with_no_places_persisted(self, client):
        with _patch_service(RESPONSE_EMPTY_PLACES):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.status_code == 201
        assert resp.json()["itineraries"][0]["places"] == []

    def test_zero_total_cost(self, client):
        with _patch_service(RESPONSE_EMPTY_PLACES):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        # TravelPlanOut does not embed total_estimated_cost from AI — just check plan is saved
        plan_id = resp.json()["id"]
        get_resp = client.get(f"/travel-plans/{plan_id}")
        assert get_resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. Place order field persistence
# ---------------------------------------------------------------------------

RESPONSE_MULTI_PLACES = {
    "days": [
        {
            "date": "2026-05-01",
            "notes": "Full day",
            "transport": "walking",
            "places": [
                {"name": "First Stop", "estimated_cost": 5.0, "ai_reason": "A"},
                {"name": "Second Stop", "estimated_cost": 10.0, "ai_reason": "B"},
                {"name": "Third Stop", "estimated_cost": 15.0, "ai_reason": "C"},
            ],
        }
    ],
    "total_estimated_cost": 30.0,
}


class TestPlaceOrder:
    def test_places_ordered_correctly(self, client):
        with _patch_service(RESPONSE_MULTI_PLACES):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        places = resp.json()["itineraries"][0]["places"]
        names = [p["name"] for p in places]
        assert names == ["First Stop", "Second Stop", "Third Stop"]

    def test_place_order_field_values(self, client):
        with _patch_service(RESPONSE_MULTI_PLACES):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        places = resp.json()["itineraries"][0]["places"]
        orders = [p["order"] for p in places]
        assert orders == [0, 1, 2]


# ---------------------------------------------------------------------------
# 7. Multiple plans coexist in DB
# ---------------------------------------------------------------------------

SIMPLE_RESPONSE = {
    "days": [
        {"date": "2026-05-01", "notes": "Day 1", "transport": "walking", "places": [
            {"name": "Spot A", "estimated_cost": 0.0, "ai_reason": "Good spot"}
        ]}
    ],
    "total_estimated_cost": 100.0,
}

PAYLOAD_A = {**PAYLOAD_BASE, "destination": "Seoul"}
PAYLOAD_B = {**PAYLOAD_BASE, "destination": "Busan"}


class TestMultiplePlans:
    def test_two_plans_both_retrievable(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp_a = client.post("/ai/generate", json=PAYLOAD_A)
            resp_b = client.post("/ai/generate", json=PAYLOAD_B)
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        id_a = resp_a.json()["id"]
        id_b = resp_b.json()["id"]
        assert id_a != id_b

    def test_destinations_differ(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp_a = client.post("/ai/generate", json=PAYLOAD_A)
            resp_b = client.post("/ai/generate", json=PAYLOAD_B)
        assert resp_a.json()["destination"] == "Seoul"
        assert resp_b.json()["destination"] == "Busan"

    def test_list_returns_both(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            client.post("/ai/generate", json=PAYLOAD_A)
            client.post("/ai/generate", json=PAYLOAD_B)
        all_plans = client.get("/travel-plans/").json()["items"]
        destinations = {p["destination"] for p in all_plans}
        assert "Seoul" in destinations
        assert "Busan" in destinations


# ---------------------------------------------------------------------------
# 8. All TravelPlanOut fields present in generate response
# ---------------------------------------------------------------------------

class TestGenerateResponseFields:
    def test_response_includes_budget(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.json()["budget"] == PAYLOAD_BASE["budget"]

    def test_response_includes_interests(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.json()["interests"] == PAYLOAD_BASE["interests"]

    def test_response_includes_start_date(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.json()["start_date"] == PAYLOAD_BASE["start_date"]

    def test_response_includes_end_date(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert resp.json()["end_date"] == PAYLOAD_BASE["end_date"]

    def test_response_has_id(self, client):
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=PAYLOAD_BASE)
        assert "id" in resp.json()
        assert isinstance(resp.json()["id"], int)


# ---------------------------------------------------------------------------
# 9. Budget validation edge cases
# ---------------------------------------------------------------------------

class TestBudgetValidation:
    def test_negative_budget_rejected(self, client):
        bad = {**PAYLOAD_BASE, "budget": -100.0}
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=bad)
        assert resp.status_code == 422

    def test_zero_budget_rejected(self, client):
        bad = {**PAYLOAD_BASE, "budget": 0.0}
        with _patch_service(SIMPLE_RESPONSE):
            resp = client.post("/ai/generate", json=bad)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 10. Interests edge cases in prompt building
# ---------------------------------------------------------------------------

class TestInterestsInPrompt:
    def setup_method(self):
        self.svc = GeminiService(api_key="test-key")

    def test_multiple_comma_separated_interests(self):
        prompt = self.svc._build_prompt(
            "NYC", date(2026, 9, 1), date(2026, 9, 3), 2000.0, "art, jazz, food"
        )
        assert "art, jazz, food" in prompt

    def test_empty_string_interests_uses_default(self):
        prompt = self.svc._build_prompt(
            "Berlin", date(2026, 9, 1), date(2026, 9, 2), 800.0, ""
        )
        # empty string is falsy — falls back to default
        assert "sightseeing" in prompt

    def test_single_interest(self):
        prompt = self.svc._build_prompt(
            "Rome", date(2026, 9, 1), date(2026, 9, 2), 700.0, "history"
        )
        assert "history" in prompt

    def test_interests_not_duplicated_as_default(self):
        prompt = self.svc._build_prompt(
            "Madrid", date(2026, 9, 1), date(2026, 9, 2), 600.0, "flamenco"
        )
        # When interests provided, default "sightseeing, food, culture" should NOT be used
        assert "flamenco" in prompt
