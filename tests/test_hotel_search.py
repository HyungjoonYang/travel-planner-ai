"""Tests for hotel search service (Task #12)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.hotel_search import HotelResult, HotelSearchResult, HotelSearchService

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_HOTEL_RESPONSE = {
    "hotels": [
        {
            "name": "Hotel Le Marais",
            "description": "Charming boutique hotel in the historic Marais district",
            "price_range": "$120-$180/night",
            "address": "5 Rue de Bretagne, 75003 Paris",
            "rating": "4.5/5",
            "amenities": ["wifi", "breakfast", "concierge"],
            "tips": "Book early for the best rates",
        },
        {
            "name": "Paris Backpackers Hostel",
            "description": "Budget-friendly hostel near the Eiffel Tower",
            "price_range": "$30-$50/night",
            "address": "10 Av. Émile Zola, 75015 Paris",
            "rating": "4.0/5",
            "amenities": ["wifi", "lockers", "kitchen"],
            "tips": "Great for solo travellers",
        },
        {
            "name": "Grand Hôtel Opéra",
            "description": "Elegant 5-star hotel steps from the Paris Opera",
            "price_range": "$300-$500/night",
            "address": "2 Rue Scribe, 75009 Paris",
            "rating": "4.8/5",
            "amenities": ["wifi", "spa", "restaurant", "concierge"],
            "tips": "Ask for a room with Opera view",
        },
    ],
    "summary": "Paris offers accommodation from budget hostels to luxury palaces.",
}


def _make_mock_client(response_text: str | None = None) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text or json.dumps(SAMPLE_HOTEL_RESPONSE)
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# HotelSearchService._build_search_prompt unit tests
# ---------------------------------------------------------------------------


class TestBuildSearchPrompt:
    def setup_method(self):
        self.svc = HotelSearchService(api_key="test-key")

    def test_includes_destination(self):
        prompt = self.svc._build_search_prompt("Paris")
        assert "Paris" in prompt

    def test_includes_date_clause_when_provided(self):
        prompt = self.svc._build_search_prompt("Paris", check_in="2026-06-01", check_out="2026-06-05")
        assert "2026-06-01" in prompt
        assert "2026-06-05" in prompt

    def test_no_date_clause_when_empty(self):
        prompt = self.svc._build_search_prompt("Paris")
        assert "to" not in prompt or "2026" not in prompt  # no date range mentioned

    def test_includes_budget_clause(self):
        prompt = self.svc._build_search_prompt("Paris", budget_per_night=150)
        assert "$150/night" in prompt

    def test_no_budget_clause_when_zero(self):
        prompt = self.svc._build_search_prompt("Paris", budget_per_night=0)
        assert "under $" not in prompt

    def test_includes_guests_clause(self):
        prompt = self.svc._build_search_prompt("Paris", guests=2)
        assert "2 guest(s)" in prompt

    def test_no_guests_clause_for_single_guest(self):
        prompt = self.svc._build_search_prompt("Paris", guests=1)
        assert "guest(s)" not in prompt

    def test_includes_json_structure(self):
        prompt = self.svc._build_search_prompt("Tokyo")
        assert '"hotels"' in prompt
        assert '"summary"' in prompt

    def test_includes_hotel_fields_in_structure(self):
        prompt = self.svc._build_search_prompt("Tokyo")
        assert '"name"' in prompt
        assert '"price_range"' in prompt
        assert '"amenities"' in prompt

    def test_summary_references_destination(self):
        prompt = self.svc._build_search_prompt("Amsterdam")
        assert "Amsterdam" in prompt


# ---------------------------------------------------------------------------
# HotelSearchService._extract_json unit tests
# ---------------------------------------------------------------------------


class TestExtractJson:
    def setup_method(self):
        self.svc = HotelSearchService(api_key="test-key")

    def test_direct_json_parse(self):
        text = json.dumps({"hotels": [], "summary": "test"})
        result = self.svc._extract_json(text)
        assert result["summary"] == "test"

    def test_json_with_leading_whitespace(self):
        text = "  \n" + json.dumps({"hotels": [], "summary": "ok"})
        result = self.svc._extract_json(text)
        assert result["summary"] == "ok"

    def test_extracts_from_markdown_fence(self):
        inner = json.dumps({"hotels": [], "summary": "fenced"})
        text = f"```json\n{inner}\n```"
        result = self.svc._extract_json(text)
        assert result["summary"] == "fenced"

    def test_extracts_from_plain_code_fence(self):
        inner = json.dumps({"hotels": [], "summary": "plain"})
        text = f"```\n{inner}\n```"
        result = self.svc._extract_json(text)
        assert result["summary"] == "plain"

    def test_extracts_bare_json_from_surrounding_text(self):
        inner = json.dumps({"hotels": [], "summary": "bare"})
        text = f"Here is the result:\n{inner}\nEnd."
        result = self.svc._extract_json(text)
        assert result["summary"] == "bare"

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No valid JSON"):
            self.svc._extract_json("no json here at all")


# ---------------------------------------------------------------------------
# HotelSearchService.search_hotels unit tests (mocked Gemini)
# ---------------------------------------------------------------------------


class TestSearchHotels:
    def setup_method(self):
        self.svc = HotelSearchService(api_key="test-key")

    def test_raises_without_api_key(self):
        svc = HotelSearchService(api_key="")
        with patch("app.hotel_search.GEMINI_API_KEY", ""):
            svc._api_key = ""
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                svc.search_hotels("Paris")

    def test_returns_hotel_search_result(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris")
        assert isinstance(result, HotelSearchResult)

    def test_destination_field(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris")
        assert result.destination == "Paris"

    def test_check_in_stored(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris", check_in="2026-06-01")
        assert result.check_in == "2026-06-01"

    def test_check_out_stored(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris", check_out="2026-06-05")
        assert result.check_out == "2026-06-05"

    def test_budget_stored(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris", budget_per_night=200)
        assert result.budget_per_night == 200

    def test_hotels_count(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris")
        assert len(result.hotels) == 3

    def test_hotel_fields_parsed(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris")
        hotel = result.hotels[0]
        assert hotel.name == "Hotel Le Marais"
        assert hotel.price_range == "$120-$180/night"
        assert hotel.rating == "4.5/5"
        assert "wifi" in hotel.amenities
        assert "Bretagne" in hotel.address

    def test_summary_populated(self):
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_hotels("Paris")
        assert "Paris" in result.summary

    def test_gemini_called_once(self):
        mock_client = _make_mock_client()
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_hotels("Paris")
        assert mock_client.models.generate_content.call_count == 1

    def test_gemini_client_receives_api_key(self):
        mock_client = _make_mock_client()
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_hotels("Paris")
        mock_genai.Client.assert_called_once_with(api_key="test-key")

    def test_empty_hotels_when_response_has_none(self):
        empty_response = json.dumps({"hotels": [], "summary": "No options found"})
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client(empty_response)
            result = self.svc.search_hotels("Nowhere")
        assert result.hotels == []
        assert result.summary == "No options found"

    def test_amenities_default_empty_list(self):
        response = json.dumps({
            "hotels": [{"name": "Simple Inn", "description": "Basic hotel"}],
            "summary": "ok",
        })
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client(response)
            result = self.svc.search_hotels("Berlin")
        assert result.hotels[0].amenities == []

    def test_uses_google_search_tool(self):
        mock_client = _make_mock_client()
        with patch("app.hotel_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            mock_genai.types = __import__("google.genai", fromlist=["types"]).types
            self.svc.search_hotels("Paris")
        # Verify that generate_content was called with a config (containing google_search tool)
        call_kwargs = mock_client.models.generate_content.call_args
        assert call_kwargs is not None


# ---------------------------------------------------------------------------
# GET /search/hotels endpoint integration tests
# ---------------------------------------------------------------------------


class TestSearchHotelsEndpoint:
    def _mock_service(self, result: HotelSearchResult | None = None):
        if result is None:
            result = HotelSearchResult(
                destination="Paris",
                check_in="2026-06-01",
                check_out="2026-06-05",
                budget_per_night=200,
                hotels=[
                    HotelResult(
                        name="Hotel Le Marais",
                        description="Charming boutique hotel",
                        price_range="$120-$180/night",
                        address="5 Rue de Bretagne, Paris",
                        rating="4.5/5",
                        amenities=["wifi", "breakfast"],
                        tips="Book early",
                    )
                ],
                summary="Paris has great hotels.",
            )
        mock_svc = MagicMock()
        mock_svc.search_hotels.return_value = result
        return patch("app.routers.search.HotelSearchService", return_value=mock_svc)

    def test_returns_200(self, client):
        with self._mock_service():
            resp = client.get("/search/hotels?destination=Paris")
        assert resp.status_code == 200

    def test_response_destination(self, client):
        with self._mock_service():
            resp = client.get("/search/hotels?destination=Paris")
        assert resp.json()["destination"] == "Paris"

    def test_response_has_hotels(self, client):
        with self._mock_service():
            resp = client.get("/search/hotels?destination=Paris")
        assert len(resp.json()["hotels"]) == 1

    def test_hotel_fields_in_response(self, client):
        with self._mock_service():
            resp = client.get("/search/hotels?destination=Paris")
        hotel = resp.json()["hotels"][0]
        assert hotel["name"] == "Hotel Le Marais"
        assert hotel["price_range"] == "$120-$180/night"
        assert hotel["rating"] == "4.5/5"
        assert "wifi" in hotel["amenities"]

    def test_response_has_summary(self, client):
        with self._mock_service():
            resp = client.get("/search/hotels?destination=Paris")
        assert "Paris" in resp.json()["summary"]

    def test_check_in_check_out_in_response(self, client):
        with self._mock_service():
            resp = client.get("/search/hotels?destination=Paris&check_in=2026-06-01&check_out=2026-06-05")
        data = resp.json()
        assert data["check_in"] == "2026-06-01"
        assert data["check_out"] == "2026-06-05"

    def test_params_forwarded_to_service(self, client):
        mock_svc = MagicMock()
        mock_svc.search_hotels.return_value = HotelSearchResult(
            destination="Tokyo", hotels=[], summary=""
        )
        with patch("app.routers.search.HotelSearchService", return_value=mock_svc):
            client.get(
                "/search/hotels?destination=Tokyo&check_in=2026-07-01&check_out=2026-07-05&budget_per_night=100&guests=2"
            )
        mock_svc.search_hotels.assert_called_once_with("Tokyo", "2026-07-01", "2026-07-05", 100, 2)

    def test_budget_zero_by_default(self, client):
        mock_svc = MagicMock()
        mock_svc.search_hotels.return_value = HotelSearchResult(
            destination="Rome", hotels=[], summary=""
        )
        with patch("app.routers.search.HotelSearchService", return_value=mock_svc):
            client.get("/search/hotels?destination=Rome")
        mock_svc.search_hotels.assert_called_once_with("Rome", "", "", 0, 1)

    def test_422_on_missing_destination(self, client):
        resp = client.get("/search/hotels")
        assert resp.status_code == 422

    def test_422_on_empty_destination(self, client):
        resp = client.get("/search/hotels?destination=")
        assert resp.status_code == 422

    def test_422_on_negative_budget(self, client):
        resp = client.get("/search/hotels?destination=Paris&budget_per_night=-50")
        assert resp.status_code == 422

    def test_422_on_zero_guests(self, client):
        resp = client.get("/search/hotels?destination=Paris&guests=0")
        assert resp.status_code == 422

    def test_503_when_no_api_key(self, client):
        with patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.get("/search/hotels?destination=Paris")
        assert resp.status_code == 503
        assert "GEMINI_API_KEY" in resp.json()["detail"]

    def test_502_when_search_fails(self, client):
        with patch("app.routers.search.HotelSearchService") as MockSvc:
            MockSvc.return_value.search_hotels.side_effect = Exception("network error")
            resp = client.get("/search/hotels?destination=Paris")
        assert resp.status_code == 502
        assert "Hotel search failed" in resp.json()["detail"]
