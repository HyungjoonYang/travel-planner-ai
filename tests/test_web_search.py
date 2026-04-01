"""Tests for web search service (Task #8)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.web_search import DestinationSearchResult, PlaceSearchResult, WebSearchService

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_SEARCH_RESPONSE = {
    "places": [
        {
            "name": "Eiffel Tower",
            "description": "Iconic iron lattice tower on the Champ de Mars",
            "category": "sightseeing",
            "address": "Champ de Mars, 5 Av. Anatole France, 75007 Paris",
            "tips": "Book tickets online to skip the queue",
        },
        {
            "name": "Le Marais Bistro",
            "description": "Classic Parisian bistro in the historic Marais district",
            "category": "food",
            "address": "15 Rue de Bretagne, 75003 Paris",
            "tips": "Try the croque-monsieur and house wine",
        },
        {
            "name": "Louvre Museum",
            "description": "World's largest art museum and a historic monument",
            "category": "sightseeing",
            "address": "Rue de Rivoli, 75001 Paris",
            "tips": "Pre-book timed entry; focus on one wing per visit",
        },
    ],
    "summary": "Paris is the City of Light, famous for art, cuisine, and iconic landmarks.",
}


def _make_mock_client(response_text: str | None = None) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text or json.dumps(SAMPLE_SEARCH_RESPONSE)
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# WebSearchService._build_search_prompt unit tests
# ---------------------------------------------------------------------------

class TestBuildSearchPrompt:
    def setup_method(self):
        self.svc = WebSearchService(api_key="test-key")

    def test_includes_destination(self):
        prompt = self.svc._build_search_prompt("Paris")
        assert "Paris" in prompt

    def test_includes_interests(self):
        prompt = self.svc._build_search_prompt("Tokyo", interests="food, temples")
        assert "food, temples" in prompt

    def test_default_interests_when_empty(self):
        prompt = self.svc._build_search_prompt("Seoul")
        assert "sightseeing" in prompt

    def test_includes_category_clause(self):
        prompt = self.svc._build_search_prompt("Rome", category="food")
        assert "focused on food" in prompt

    def test_no_category_clause_when_empty(self):
        prompt = self.svc._build_search_prompt("Rome")
        assert "focused on" not in prompt

    def test_includes_json_structure(self):
        prompt = self.svc._build_search_prompt("Berlin")
        assert '"places"' in prompt
        assert '"summary"' in prompt

    def test_summary_references_destination(self):
        prompt = self.svc._build_search_prompt("Amsterdam")
        assert "Amsterdam" in prompt


# ---------------------------------------------------------------------------
# WebSearchService._extract_json unit tests
# ---------------------------------------------------------------------------

class TestExtractJson:
    def setup_method(self):
        self.svc = WebSearchService(api_key="test-key")

    def test_direct_json_parse(self):
        text = json.dumps({"places": [], "summary": "test"})
        result = self.svc._extract_json(text)
        assert result["summary"] == "test"

    def test_json_with_leading_whitespace(self):
        text = "  \n" + json.dumps({"places": [], "summary": "ok"})
        result = self.svc._extract_json(text)
        assert result["summary"] == "ok"

    def test_extracts_from_markdown_fence(self):
        inner = json.dumps({"places": [], "summary": "fenced"})
        text = f"```json\n{inner}\n```"
        result = self.svc._extract_json(text)
        assert result["summary"] == "fenced"

    def test_extracts_from_plain_code_fence(self):
        inner = json.dumps({"places": [], "summary": "plain"})
        text = f"```\n{inner}\n```"
        result = self.svc._extract_json(text)
        assert result["summary"] == "plain"

    def test_extracts_bare_json_from_surrounding_text(self):
        inner = json.dumps({"places": [], "summary": "bare"})
        text = f"Here is the result:\n{inner}\nEnd."
        result = self.svc._extract_json(text)
        assert result["summary"] == "bare"

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No valid JSON"):
            self.svc._extract_json("no json here at all")


# ---------------------------------------------------------------------------
# WebSearchService.search_places unit tests (mocked Gemini)
# ---------------------------------------------------------------------------

class TestSearchPlaces:
    def setup_method(self):
        self.svc = WebSearchService(api_key="test-key")

    def test_raises_without_api_key(self):
        svc = WebSearchService(api_key="")
        with patch("app.web_search.GEMINI_API_KEY", ""):
            svc._api_key = ""
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                svc.search_places("Paris")

    def test_returns_destination_search_result(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris")
        assert isinstance(result, DestinationSearchResult)

    def test_destination_field(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris")
        assert result.destination == "Paris"

    def test_query_includes_destination(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris")
        assert "Paris" in result.query

    def test_query_includes_interests(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris", interests="art, cafes")
        assert "art, cafes" in result.query

    def test_places_count(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris")
        assert len(result.places) == 3

    def test_place_fields_parsed(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris")
        place = result.places[0]
        assert place.name == "Eiffel Tower"
        assert place.category == "sightseeing"
        assert "Champ de Mars" in place.address
        assert "queue" in place.tips

    def test_summary_populated(self):
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_places("Paris")
        assert "Paris" in result.summary

    def test_gemini_called_with_google_search_tool(self):
        mock_client = _make_mock_client()
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_places("Paris")
        call_kwargs = mock_client.models.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
        # Verify generate_content was called once
        assert mock_client.models.generate_content.call_count == 1

    def test_gemini_client_receives_api_key(self):
        mock_client = _make_mock_client()
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_places("Paris")
        mock_genai.Client.assert_called_once_with(api_key="test-key")

    def test_empty_places_when_response_has_none(self):
        empty_response = json.dumps({"places": [], "summary": "Empty destination"})
        with patch("app.web_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client(empty_response)
            result = self.svc.search_places("Nowhere")
        assert result.places == []
        assert result.summary == "Empty destination"


# ---------------------------------------------------------------------------
# GET /search/places endpoint integration tests
# ---------------------------------------------------------------------------

class TestSearchPlacesEndpoint:
    def _mock_service(self, result: DestinationSearchResult | None = None):
        if result is None:
            result = DestinationSearchResult(
                destination="Paris",
                query="Paris",
                places=[
                    PlaceSearchResult(
                        name="Eiffel Tower",
                        description="Iconic tower",
                        category="sightseeing",
                        address="Champ de Mars, Paris",
                        tips="Book online",
                    )
                ],
                summary="Paris is the City of Light.",
            )
        mock_svc = MagicMock()
        mock_svc.search_places.return_value = result
        return patch("app.routers.search.WebSearchService", return_value=mock_svc)

    def test_returns_200(self, client):
        with self._mock_service():
            resp = client.get("/search/places?destination=Paris")
        assert resp.status_code == 200

    def test_response_destination(self, client):
        with self._mock_service():
            resp = client.get("/search/places?destination=Paris")
        assert resp.json()["destination"] == "Paris"

    def test_response_has_places(self, client):
        with self._mock_service():
            resp = client.get("/search/places?destination=Paris")
        assert len(resp.json()["places"]) == 1

    def test_place_fields_in_response(self, client):
        with self._mock_service():
            resp = client.get("/search/places?destination=Paris")
        place = resp.json()["places"][0]
        assert place["name"] == "Eiffel Tower"
        assert place["category"] == "sightseeing"

    def test_response_has_summary(self, client):
        with self._mock_service():
            resp = client.get("/search/places?destination=Paris")
        assert "Paris" in resp.json()["summary"]

    def test_interests_param_forwarded(self, client):
        mock_svc = MagicMock()
        mock_svc.search_places.return_value = DestinationSearchResult(
            destination="Tokyo", query="Tokyo food", places=[], summary=""
        )
        with patch("app.routers.search.WebSearchService", return_value=mock_svc):
            client.get("/search/places?destination=Tokyo&interests=food")
        mock_svc.search_places.assert_called_once_with("Tokyo", "food", "")

    def test_category_param_forwarded(self, client):
        mock_svc = MagicMock()
        mock_svc.search_places.return_value = DestinationSearchResult(
            destination="Rome", query="Rome", places=[], summary=""
        )
        with patch("app.routers.search.WebSearchService", return_value=mock_svc):
            client.get("/search/places?destination=Rome&category=sightseeing")
        mock_svc.search_places.assert_called_once_with("Rome", "", "sightseeing")

    def test_422_on_missing_destination(self, client):
        resp = client.get("/search/places")
        assert resp.status_code == 422

    def test_422_on_empty_destination(self, client):
        resp = client.get("/search/places?destination=")
        assert resp.status_code == 422

    def test_503_when_no_api_key(self, client):
        with patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.get("/search/places?destination=Paris")
        assert resp.status_code == 503
        assert "GEMINI_API_KEY" in resp.json()["detail"]

    def test_502_when_search_fails(self, client):
        with patch("app.routers.search.WebSearchService") as MockSvc:
            MockSvc.return_value.search_places.side_effect = Exception("network error")
            resp = client.get("/search/places?destination=Paris")
        assert resp.status_code == 502
        assert "Search failed" in resp.json()["detail"]
