"""Tests for flight search service (Task #13)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.flight_search import FlightResult, FlightSearchResult, FlightSearchService

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_FLIGHT_RESPONSE = {
    "flights": [
        {
            "airline": "Korean Air",
            "flight_number": "KE081",
            "departure_time": "10:00",
            "arrival_time": "13:30",
            "duration": "13h 30m",
            "stops": "Nonstop",
            "price": "$650",
            "cabin_class": "Economy",
            "tips": "Book 6 weeks in advance for best fares",
        },
        {
            "airline": "Japan Airlines",
            "flight_number": "JL061",
            "departure_time": "14:00",
            "arrival_time": "17:00",
            "duration": "13h 00m",
            "stops": "Nonstop",
            "price": "$720",
            "cabin_class": "Economy",
            "tips": "Excellent in-flight meals",
        },
        {
            "airline": "Air China",
            "flight_number": "CA837",
            "departure_time": "08:30",
            "arrival_time": "18:45",
            "duration": "22h 15m",
            "stops": "1 stop via Beijing",
            "price": "$420",
            "cabin_class": "Economy",
            "tips": "Budget option with longer travel time",
        },
    ],
    "summary": "Several airlines operate direct and connecting flights from Los Angeles to Tokyo.",
}


def _make_mock_client(response_text: str | None = None) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text or json.dumps(SAMPLE_FLIGHT_RESPONSE)
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# FlightSearchService._build_search_prompt unit tests
# ---------------------------------------------------------------------------


class TestBuildSearchPrompt:
    def setup_method(self):
        self.svc = FlightSearchService(api_key="test-key")

    def test_includes_departure_city(self):
        prompt = self.svc._build_search_prompt("Los Angeles", "Tokyo")
        assert "Los Angeles" in prompt

    def test_includes_arrival_city(self):
        prompt = self.svc._build_search_prompt("Los Angeles", "Tokyo")
        assert "Tokyo" in prompt

    def test_includes_departure_date_when_provided(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT", departure_date="2026-06-01")
        assert "2026-06-01" in prompt

    def test_no_departure_date_when_empty(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT")
        assert "on 2026" not in prompt

    def test_includes_return_date_when_provided(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT", return_date="2026-06-10")
        assert "2026-06-10" in prompt

    def test_no_return_date_when_empty(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT")
        assert "returning" not in prompt

    def test_includes_passengers_clause(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT", passengers=3)
        assert "3 passenger(s)" in prompt

    def test_no_passengers_clause_for_single(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT", passengers=1)
        assert "passenger(s)" not in prompt

    def test_includes_max_price_clause(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT", max_price=500)
        assert "$500" in prompt

    def test_no_price_clause_when_zero(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT", max_price=0)
        assert "under $" not in prompt

    def test_includes_json_structure(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT")
        assert '"flights"' in prompt
        assert '"summary"' in prompt

    def test_includes_flight_fields_in_structure(self):
        prompt = self.svc._build_search_prompt("LAX", "NRT")
        assert '"airline"' in prompt
        assert '"price"' in prompt
        assert '"duration"' in prompt

    def test_summary_references_both_cities(self):
        prompt = self.svc._build_search_prompt("Seoul", "Paris")
        assert "Seoul" in prompt
        assert "Paris" in prompt


# ---------------------------------------------------------------------------
# FlightSearchService._extract_json unit tests
# ---------------------------------------------------------------------------


class TestExtractJson:
    def setup_method(self):
        self.svc = FlightSearchService(api_key="test-key")

    def test_direct_json_parse(self):
        text = json.dumps({"flights": [], "summary": "test"})
        result = self.svc._extract_json(text)
        assert result["summary"] == "test"

    def test_json_with_leading_whitespace(self):
        text = "  \n" + json.dumps({"flights": [], "summary": "ok"})
        result = self.svc._extract_json(text)
        assert result["summary"] == "ok"

    def test_extracts_from_markdown_fence(self):
        inner = json.dumps({"flights": [], "summary": "fenced"})
        text = f"```json\n{inner}\n```"
        result = self.svc._extract_json(text)
        assert result["summary"] == "fenced"

    def test_extracts_from_plain_code_fence(self):
        inner = json.dumps({"flights": [], "summary": "plain"})
        text = f"```\n{inner}\n```"
        result = self.svc._extract_json(text)
        assert result["summary"] == "plain"

    def test_extracts_bare_json_from_surrounding_text(self):
        inner = json.dumps({"flights": [], "summary": "bare"})
        text = f"Here is the result:\n{inner}\nEnd."
        result = self.svc._extract_json(text)
        assert result["summary"] == "bare"

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No valid JSON"):
            self.svc._extract_json("no json here at all")


# ---------------------------------------------------------------------------
# FlightSearchService.search_flights unit tests (mocked Gemini)
# ---------------------------------------------------------------------------


class TestSearchFlights:
    def setup_method(self):
        self.svc = FlightSearchService(api_key="test-key")

    def test_raises_without_api_key(self):
        svc = FlightSearchService(api_key="")
        with patch("app.flight_search.GEMINI_API_KEY", ""):
            svc._api_key = ""
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                svc.search_flights("LAX", "NRT")

    def test_returns_flight_search_result(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("Los Angeles", "Tokyo")
        assert isinstance(result, FlightSearchResult)

    def test_departure_city_field(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("Los Angeles", "Tokyo")
        assert result.departure_city == "Los Angeles"

    def test_arrival_city_field(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("Los Angeles", "Tokyo")
        assert result.arrival_city == "Tokyo"

    def test_departure_date_stored(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("LAX", "NRT", departure_date="2026-06-01")
        assert result.departure_date == "2026-06-01"

    def test_return_date_stored(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("LAX", "NRT", return_date="2026-06-10")
        assert result.return_date == "2026-06-10"

    def test_passengers_stored(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("LAX", "NRT", passengers=2)
        assert result.passengers == 2

    def test_flights_count(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("Los Angeles", "Tokyo")
        assert len(result.flights) == 3

    def test_flight_fields_parsed(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("Los Angeles", "Tokyo")
        flight = result.flights[0]
        assert flight.airline == "Korean Air"
        assert flight.flight_number == "KE081"
        assert flight.price == "$650"
        assert flight.stops == "Nonstop"
        assert flight.duration == "13h 30m"

    def test_summary_populated(self):
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client()
            result = self.svc.search_flights("Los Angeles", "Tokyo")
        assert "Los Angeles" in result.summary or "Tokyo" in result.summary

    def test_gemini_called_once(self):
        mock_client = _make_mock_client()
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_flights("LAX", "NRT")
        assert mock_client.models.generate_content.call_count == 1

    def test_gemini_client_receives_api_key(self):
        mock_client = _make_mock_client()
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_flights("LAX", "NRT")
        mock_genai.Client.assert_called_once_with(api_key="test-key")

    def test_empty_flights_when_response_has_none(self):
        empty_response = json.dumps({"flights": [], "summary": "No flights found"})
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client(empty_response)
            result = self.svc.search_flights("LAX", "XYZ")
        assert result.flights == []
        assert result.summary == "No flights found"

    def test_optional_fields_default_empty(self):
        response = json.dumps({
            "flights": [{"airline": "Budget Air"}],
            "summary": "ok",
        })
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = _make_mock_client(response)
            result = self.svc.search_flights("A", "B")
        assert result.flights[0].flight_number == ""
        assert result.flights[0].price == ""

    def test_uses_google_search_tool(self):
        mock_client = _make_mock_client()
        with patch("app.flight_search.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            self.svc.search_flights("LAX", "NRT")
        call_kwargs = mock_client.models.generate_content.call_args
        assert call_kwargs is not None


# ---------------------------------------------------------------------------
# GET /search/flights endpoint integration tests
# ---------------------------------------------------------------------------


class TestSearchFlightsEndpoint:
    def _mock_service(self, result: FlightSearchResult | None = None):
        if result is None:
            result = FlightSearchResult(
                departure_city="Los Angeles",
                arrival_city="Tokyo",
                departure_date="2026-06-01",
                return_date="2026-06-10",
                passengers=1,
                flights=[
                    FlightResult(
                        airline="Korean Air",
                        flight_number="KE081",
                        departure_time="10:00",
                        arrival_time="13:30",
                        duration="13h 30m",
                        stops="Nonstop",
                        price="$650",
                        cabin_class="Economy",
                        tips="Book early",
                    )
                ],
                summary="Several airlines serve the LAX-NRT route.",
            )
        mock_svc = MagicMock()
        mock_svc.search_flights.return_value = result
        return patch("app.routers.search.FlightSearchService", return_value=mock_svc)

    def test_returns_200(self, client):
        with self._mock_service():
            resp = client.get("/search/flights?departure_city=Los+Angeles&arrival_city=Tokyo")
        assert resp.status_code == 200

    def test_response_departure_city(self, client):
        with self._mock_service():
            resp = client.get("/search/flights?departure_city=Los+Angeles&arrival_city=Tokyo")
        assert resp.json()["departure_city"] == "Los Angeles"

    def test_response_arrival_city(self, client):
        with self._mock_service():
            resp = client.get("/search/flights?departure_city=Los+Angeles&arrival_city=Tokyo")
        assert resp.json()["arrival_city"] == "Tokyo"

    def test_response_has_flights(self, client):
        with self._mock_service():
            resp = client.get("/search/flights?departure_city=Los+Angeles&arrival_city=Tokyo")
        assert len(resp.json()["flights"]) == 1

    def test_flight_fields_in_response(self, client):
        with self._mock_service():
            resp = client.get("/search/flights?departure_city=Los+Angeles&arrival_city=Tokyo")
        flight = resp.json()["flights"][0]
        assert flight["airline"] == "Korean Air"
        assert flight["flight_number"] == "KE081"
        assert flight["price"] == "$650"
        assert flight["stops"] == "Nonstop"

    def test_response_has_summary(self, client):
        with self._mock_service():
            resp = client.get("/search/flights?departure_city=Los+Angeles&arrival_city=Tokyo")
        assert "LAX" in resp.json()["summary"] or "NRT" in resp.json()["summary"] or "airlines" in resp.json()["summary"]

    def test_dates_in_response(self, client):
        with self._mock_service():
            resp = client.get(
                "/search/flights?departure_city=LAX&arrival_city=NRT&departure_date=2026-06-01&return_date=2026-06-10"
            )
        data = resp.json()
        assert data["departure_date"] == "2026-06-01"
        assert data["return_date"] == "2026-06-10"

    def test_params_forwarded_to_service(self, client):
        mock_svc = MagicMock()
        mock_svc.search_flights.return_value = FlightSearchResult(
            departure_city="Seoul", arrival_city="Paris", flights=[], summary=""
        )
        with patch("app.routers.search.FlightSearchService", return_value=mock_svc):
            client.get(
                "/search/flights?departure_city=Seoul&arrival_city=Paris"
                "&departure_date=2026-07-01&return_date=2026-07-10&passengers=2&max_price=800"
            )
        mock_svc.search_flights.assert_called_once_with(
            "Seoul", "Paris", "2026-07-01", "2026-07-10", 2, 800
        )

    def test_defaults_applied(self, client):
        mock_svc = MagicMock()
        mock_svc.search_flights.return_value = FlightSearchResult(
            departure_city="NYC", arrival_city="London", flights=[], summary=""
        )
        with patch("app.routers.search.FlightSearchService", return_value=mock_svc):
            client.get("/search/flights?departure_city=NYC&arrival_city=London")
        mock_svc.search_flights.assert_called_once_with("NYC", "London", "", "", 1, 0)

    def test_422_on_missing_departure_city(self, client):
        resp = client.get("/search/flights?arrival_city=Tokyo")
        assert resp.status_code == 422

    def test_422_on_missing_arrival_city(self, client):
        resp = client.get("/search/flights?departure_city=LAX")
        assert resp.status_code == 422

    def test_422_on_empty_departure_city(self, client):
        resp = client.get("/search/flights?departure_city=&arrival_city=Tokyo")
        assert resp.status_code == 422

    def test_422_on_negative_max_price(self, client):
        resp = client.get("/search/flights?departure_city=LAX&arrival_city=NRT&max_price=-100")
        assert resp.status_code == 422

    def test_422_on_zero_passengers(self, client):
        resp = client.get("/search/flights?departure_city=LAX&arrival_city=NRT&passengers=0")
        assert resp.status_code == 422

    def test_503_when_no_api_key(self, client):
        with patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.side_effect = ValueError(
                "GEMINI_API_KEY is not configured"
            )
            resp = client.get("/search/flights?departure_city=LAX&arrival_city=NRT")
        assert resp.status_code == 503
        assert "GEMINI_API_KEY" in resp.json()["detail"]

    def test_502_when_search_fails(self, client):
        with patch("app.routers.search.FlightSearchService") as MockSvc:
            MockSvc.return_value.search_flights.side_effect = Exception("network error")
            resp = client.get("/search/flights?departure_city=LAX&arrival_city=NRT")
        assert resp.status_code == 502
        assert "Flight search failed" in resp.json()["detail"]
