"""Tests for Task #9: Structured output (day-by-day itinerary JSON).

Covers:
- response_schema passed to GenerateContentConfig (Gemini schema enforcement)
- Prompt no longer embeds a raw JSON template (schema handles structure)
- model_validate_json used for parsing
- POST /ai/preview endpoint (structured itinerary without DB persistence)
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch


from app.ai import AIItineraryResult, GeminiService

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

SAMPLE_AI_RESPONSE = {
    "days": [
        {
            "date": "2026-06-01",
            "notes": "Explore central Paris",
            "transport": "walking",
            "places": [
                {
                    "name": "Eiffel Tower",
                    "category": "sightseeing",
                    "address": "Champ de Mars, 5 Av. Anatole France",
                    "estimated_cost": 28.0,
                    "ai_reason": "Iconic Paris landmark",
                },
                {
                    "name": "Café de Flore",
                    "category": "cafe",
                    "address": "172 Bd Saint-Germain, 75006 Paris",
                    "estimated_cost": 12.0,
                    "ai_reason": "Historic Parisian café, great atmosphere",
                },
            ],
        },
        {
            "date": "2026-06-02",
            "notes": "Museums and culture",
            "transport": "subway",
            "places": [
                {
                    "name": "Louvre Museum",
                    "category": "sightseeing",
                    "address": "Rue de Rivoli, 75001 Paris",
                    "estimated_cost": 17.0,
                    "ai_reason": "World's largest art museum",
                },
            ],
        },
    ],
    "total_estimated_cost": 800.0,
}

GENERATE_PAYLOAD = {
    "destination": "Paris",
    "start_date": "2026-06-01",
    "end_date": "2026-06-02",
    "budget": 1200.0,
    "interests": "art, food",
    "status": "draft",
}


def _make_mock_client() -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(SAMPLE_AI_RESPONSE)
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# Structured output: response_schema in GenerateContentConfig
# ---------------------------------------------------------------------------

class TestResponseSchema:
    """Verify that generate_itinerary passes response_schema to Gemini."""

    def setup_method(self):
        self.svc = GeminiService(api_key="test-key")

    def test_response_schema_is_passed(self):
        mock_client = _make_mock_client()
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.response_schema is AIItineraryResult

    def test_response_mime_type_is_json(self):
        mock_client = _make_mock_client()
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.response_mime_type == "application/json"

    def test_returns_ai_itinerary_result_type(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        assert isinstance(result, AIItineraryResult)

    def test_days_parsed_correctly(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        assert len(result.days) == 2

    def test_total_cost_parsed(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        assert result.total_estimated_cost == 800.0

    def test_places_parsed_in_first_day(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        assert result.days[0].places[0].name == "Eiffel Tower"

    def test_place_fields_fully_parsed(self):
        with patch("app.ai.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.generate_itinerary("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0)
        p = result.days[0].places[0]
        assert p.category == "sightseeing"
        assert p.estimated_cost == 28.0
        assert "landmark" in p.ai_reason


# ---------------------------------------------------------------------------
# Prompt simplification: no raw JSON template in prompt
# ---------------------------------------------------------------------------

class TestPromptSimplified:
    """Verify prompt no longer contains an embedded JSON structure template."""

    def setup_method(self):
        self.svc = GeminiService(api_key="test-key")

    def test_prompt_has_no_json_template_braces(self):
        prompt = self.svc._build_prompt("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0, "art")
        # The old prompt contained a literal JSON template like {"days": [...]}
        # With response_schema, the schema handles structure — prompt should not embed it
        assert '"days"' not in prompt

    def test_prompt_still_includes_destination(self):
        prompt = self.svc._build_prompt("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0, "art")
        assert "Paris" in prompt

    def test_prompt_still_includes_budget(self):
        prompt = self.svc._build_prompt("Paris", date(2026, 6, 1), date(2026, 6, 2), 1200.0, "art")
        assert "1200" in prompt

    def test_prompt_still_includes_interests(self):
        prompt = self.svc._build_prompt("Tokyo", date(2026, 5, 1), date(2026, 5, 3), 500.0, "anime, ramen")
        assert "anime, ramen" in prompt

    def test_prompt_mentions_num_days(self):
        prompt = self.svc._build_prompt("London", date(2026, 5, 1), date(2026, 5, 5), 2000.0, "")
        assert "5 days" in prompt

    def test_prompt_mentions_date_format(self):
        prompt = self.svc._build_prompt("Seoul", date(2026, 5, 1), date(2026, 5, 2), 800.0, "")
        assert "YYYY-MM-DD" in prompt


# ---------------------------------------------------------------------------
# POST /ai/preview endpoint
# ---------------------------------------------------------------------------

class TestPreviewEndpoint:
    """POST /ai/preview returns structured itinerary without DB persistence."""

    def _patched_service(self):
        mock_service = MagicMock()
        mock_service.generate_itinerary.return_value = AIItineraryResult.model_validate(
            SAMPLE_AI_RESPONSE
        )
        return patch("app.routers.ai_plans.GeminiService", return_value=mock_service)

    def test_returns_200(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        assert resp.status_code == 200

    def test_response_has_days(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        assert len(resp.json()["days"]) == 2

    def test_response_has_total_cost(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        assert resp.json()["total_estimated_cost"] == 800.0

    def test_first_day_places_returned(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        places = resp.json()["days"][0]["places"]
        assert len(places) == 2
        assert places[0]["name"] == "Eiffel Tower"

    def test_does_not_persist_to_db(self, client):
        # Count plans before
        count_before = len(client.get("/travel-plans/").json())
        with self._patched_service():
            client.post("/ai/preview", json=GENERATE_PAYLOAD)
        count_after = len(client.get("/travel-plans/").json())
        assert count_after == count_before

    def test_503_when_no_api_key(self, client):
        with patch("app.routers.ai_plans.GeminiService") as MockSvc:
            MockSvc.return_value.generate_itinerary.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        assert resp.status_code == 503

    def test_502_when_ai_fails(self, client):
        with patch("app.routers.ai_plans.GeminiService") as MockSvc:
            MockSvc.return_value.generate_itinerary.side_effect = Exception("upstream error")
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        assert resp.status_code == 502
        assert "AI generation failed" in resp.json()["detail"]

    def test_422_on_missing_destination(self, client):
        resp = client.post("/ai/preview", json={"budget": 500.0})
        assert resp.status_code == 422

    def test_422_on_empty_destination(self, client):
        bad = {**GENERATE_PAYLOAD, "destination": ""}
        with self._patched_service():
            resp = client.post("/ai/preview", json=bad)
        assert resp.status_code == 422

    def test_second_day_returned(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        day2 = resp.json()["days"][1]
        assert day2["date"] == "2026-06-02"
        assert day2["places"][0]["name"] == "Louvre Museum"

    def test_place_ai_reason_returned(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        place = resp.json()["days"][0]["places"][0]
        assert "landmark" in place["ai_reason"]

    def test_place_estimated_cost_returned(self, client):
        with self._patched_service():
            resp = client.post("/ai/preview", json=GENERATE_PAYLOAD)
        place = resp.json()["days"][0]["places"][0]
        assert place["estimated_cost"] == 28.0
