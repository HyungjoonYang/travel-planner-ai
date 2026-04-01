"""Tests for Gemini AI integration (Task #7)."""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.ai import AIDayItinerary, AIItineraryResult, AIPlace, GeminiService

# ---------------------------------------------------------------------------
# Sample fixture data
# ---------------------------------------------------------------------------

SAMPLE_AI_RESPONSE = {
    "days": [
        {
            "date": "2026-05-01",
            "notes": "Explore Shinjuku area",
            "transport": "subway",
            "places": [
                {
                    "name": "Shinjuku Gyoen",
                    "category": "sightseeing",
                    "address": "11 Naitomachi, Shinjuku",
                    "estimated_cost": 5.0,
                    "ai_reason": "Famous garden with cherry blossoms",
                },
                {
                    "name": "Ichiran Ramen",
                    "category": "food",
                    "address": "1-1 Kabukicho, Shinjuku",
                    "estimated_cost": 15.0,
                    "ai_reason": "Best solo ramen experience in Tokyo",
                },
            ],
        },
        {
            "date": "2026-05-02",
            "notes": "Visit Asakusa",
            "transport": "walking",
            "places": [
                {
                    "name": "Senso-ji Temple",
                    "category": "sightseeing",
                    "address": "2-3-1 Asakusa, Taito",
                    "estimated_cost": 0.0,
                    "ai_reason": "Oldest temple in Tokyo, must-visit",
                },
            ],
        },
    ],
    "total_estimated_cost": 350.0,
}


def _make_mock_client() -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(SAMPLE_AI_RESPONSE)
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# GeminiService._build_prompt unit tests
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.svc = GeminiService(api_key="test-key")

    def test_includes_destination(self):
        prompt = self.svc._build_prompt("Tokyo", date(2026, 5, 1), date(2026, 5, 3), 1000.0, "food")
        assert "Tokyo" in prompt

    def test_includes_start_date(self):
        prompt = self.svc._build_prompt("Paris", date(2026, 6, 1), date(2026, 6, 2), 500.0, "")
        assert "2026-06-01" in prompt

    def test_includes_end_date(self):
        prompt = self.svc._build_prompt("Paris", date(2026, 6, 1), date(2026, 6, 2), 500.0, "")
        assert "2026-06-02" in prompt

    def test_includes_budget(self):
        prompt = self.svc._build_prompt("Seoul", date(2026, 5, 1), date(2026, 5, 2), 800.0, "")
        assert "800" in prompt

    def test_includes_interests(self):
        prompt = self.svc._build_prompt("Bali", date(2026, 7, 1), date(2026, 7, 3), 1200.0, "beach, spa")
        assert "beach, spa" in prompt

    def test_default_interests_when_empty(self):
        prompt = self.svc._build_prompt("NYC", date(2026, 5, 1), date(2026, 5, 2), 2000.0, "")
        assert "sightseeing" in prompt

    def test_calculates_num_days(self):
        # 5-day trip: May 1 through May 5
        prompt = self.svc._build_prompt("London", date(2026, 5, 1), date(2026, 5, 5), 3000.0, "")
        assert "5 days" in prompt

    def test_single_day_trip(self):
        prompt = self.svc._build_prompt("Singapore", date(2026, 8, 10), date(2026, 8, 10), 200.0, "")
        assert "1 days" in prompt


# ---------------------------------------------------------------------------
# GeminiService.generate_itinerary unit tests (mocked Gemini)
# ---------------------------------------------------------------------------

class TestGenerateItinerary:
    def setup_method(self):
        self.svc = GeminiService(api_key="test-key")

    def test_raises_without_api_key(self):
        svc = GeminiService(api_key="")
        with patch("app.ai.GEMINI_API_KEY", ""):
            svc._api_key = ""
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)

    def test_returns_ai_itinerary_result(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        assert isinstance(result, AIItineraryResult)

    def test_correct_number_of_days(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        assert len(result.days) == 2

    def test_day_has_places(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        assert len(result.days[0].places) == 2

    def test_place_fields_parsed_correctly(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        place = result.days[0].places[0]
        assert place.name == "Shinjuku Gyoen"
        assert place.category == "sightseeing"
        assert place.estimated_cost == 5.0
        assert "cherry blossoms" in place.ai_reason

    def test_total_estimated_cost(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        assert result.total_estimated_cost == 350.0

    def test_day_transport_and_notes(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        assert result.days[0].transport == "subway"
        assert "Shinjuku" in result.days[0].notes

    def test_gemini_client_called_once(self):
        mock_client = _make_mock_client()
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        assert mock_client.models.generate_content.call_count == 1

    def test_gemini_client_receives_api_key(self):
        mock_client = _make_mock_client()
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 2), 1000.0)
        mock_genai.Client.assert_called_once_with(api_key="test-key")


# ---------------------------------------------------------------------------
# POST /ai/generate endpoint integration tests
# ---------------------------------------------------------------------------

GENERATE_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-05-01",
    "end_date": "2026-05-02",
    "budget": 1000.0,
    "interests": "food, temples",
    "status": "draft",
}


class TestAIGenerateEndpoint:
    def _patched_service(self):
        """Context manager that patches GeminiService with SAMPLE_AI_RESPONSE."""
        mock_service = MagicMock()
        mock_service.generate_itinerary.return_value = AIItineraryResult.model_validate(
            SAMPLE_AI_RESPONSE
        )
        patcher = patch("app.routers.ai_plans.GeminiService", return_value=mock_service)
        return patcher

    def test_returns_201(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 201

    def test_response_destination(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        assert resp.json()["destination"] == "Tokyo"

    def test_response_status(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        assert resp.json()["status"] == "draft"

    def test_creates_itineraries(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        assert len(resp.json()["itineraries"]) == 2

    def test_itinerary_places_persisted(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        day1_places = resp.json()["itineraries"][0]["places"]
        assert len(day1_places) == 2
        assert day1_places[0]["name"] == "Shinjuku Gyoen"

    def test_place_ai_reason_persisted(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        place = resp.json()["itineraries"][0]["places"][0]
        assert "cherry blossoms" in place["ai_reason"]

    def test_place_estimated_cost_persisted(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        place = resp.json()["itineraries"][0]["places"][0]
        assert place["estimated_cost"] == 5.0

    def test_503_when_no_api_key(self, client):
        with patch("app.routers.ai_plans.GeminiService") as MockSvc:
            MockSvc.return_value.generate_itinerary.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 503
        assert "GEMINI_API_KEY" in resp.json()["detail"]

    def test_502_when_ai_fails(self, client):
        with patch("app.routers.ai_plans.GeminiService") as MockSvc:
            MockSvc.return_value.generate_itinerary.side_effect = Exception("network error")
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        assert resp.status_code == 502
        assert "AI generation failed" in resp.json()["detail"]

    def test_422_on_missing_destination(self, client):
        resp = client.post("/ai/generate", json={"budget": 500.0})
        assert resp.status_code == 422

    def test_422_on_empty_destination(self, client):
        bad = {**GENERATE_PAYLOAD, "destination": ""}
        with self._patched_service():
            resp = client.post("/ai/generate", json=bad)
        assert resp.status_code == 422

    def test_plan_retrievable_after_generate(self, client):
        with self._patched_service():
            gen_resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        plan_id = gen_resp.json()["id"]
        get_resp = client.get(f"/travel-plans/{plan_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["destination"] == "Tokyo"

    def test_second_day_places_persisted(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        day2_places = resp.json()["itineraries"][1]["places"]
        assert len(day2_places) == 1
        assert day2_places[0]["name"] == "Senso-ji Temple"

    def test_place_order_preserved(self, client):
        with self._patched_service():
            resp = client.post("/ai/generate", json=GENERATE_PAYLOAD)
        places = resp.json()["itineraries"][0]["places"]
        assert places[0]["name"] == "Shinjuku Gyoen"
        assert places[1]["name"] == "Ichiran Ramen"
