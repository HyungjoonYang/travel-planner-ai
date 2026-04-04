"""Tests for Task #44: chat.js dashboard rendering (plan_update / day_update / search_results).

Verifies backend emits plan_update data with destination, dates, budget so the frontend
can render the plan overview and budget bar; verifies search_results structure for the
expandable agent detail panel.
"""

from unittest.mock import MagicMock, patch

from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
from app.chat import ChatService, Intent, SESSION_TTL_SECONDS
from app.flight_search import FlightResult, FlightSearchResult
from app.hotel_search import HotelResult, HotelSearchResult
from app.web_search import DestinationSearchResult, PlaceSearchResult

import asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect(service, session_id, message):
    async def _run():
        events = []
        async for e in service.process_message(session_id, message):
            events.append(e)
        return events
    return asyncio.run(_run())


def _make_svc(gemini=None, web=None, hotel=None, flight=None):
    return ChatService(
        api_key="",
        ttl_seconds=SESSION_TTL_SECONDS,
        gemini_service=gemini or MagicMock(),
        web_search_service=web or MagicMock(),
        hotel_search_service=hotel or MagicMock(),
        flight_search_service=flight or MagicMock(),
    )


def _fake_itinerary():
    return AIItineraryResult(
        days=[
            AIDayItinerary(
                date="2026-05-01",
                notes="Day 1",
                places=[
                    AIPlace(name="Senso-ji", category="sightseeing", estimated_cost=0.0),
                    AIPlace(name="Ramen shop", category="food", estimated_cost=15.0),
                ],
            ),
            AIDayItinerary(
                date="2026-05-02",
                notes="Day 2",
                places=[
                    AIPlace(name="Shibuya", category="sightseeing", estimated_cost=0.0),
                ],
            ),
        ],
        total_estimated_cost=500.0,
    )


def _fake_hotels():
    return HotelSearchResult(
        destination="도쿄",
        hotels=[
            HotelResult(name="Hotel A", price_range="$100/night", rating="4.5"),
            HotelResult(name="Hotel B", price_range="$80/night", rating="4.0"),
        ],
    )


def _fake_flights():
    return FlightSearchResult(
        departure_city="Seoul",
        arrival_city="도쿄",
        flights=[FlightResult(airline="Korean Air", price="$300")],
    )


def _fake_places():
    return DestinationSearchResult(
        destination="도쿄",
        query="도쿄 food",
        places=[
            PlaceSearchResult(name="Tsukiji", category="food"),
            PlaceSearchResult(name="Harajuku", category="shopping"),
        ],
    )


# ---------------------------------------------------------------------------
# plan_update event shape (used by handlePlanUpdate in chat.js)
# ---------------------------------------------------------------------------

class TestPlanUpdateEventShape:
    """plan_update data must include destination, dates, budget for the overview UI."""

    def _get_plan_update(self, intent_extra=None):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _fake_itinerary()
        svc = _make_svc(gemini=mock_gemini)
        session = svc.create_session()
        intent = Intent(
            action="create_plan",
            destination="도쿄",
            start_date="2026-05-01",
            end_date="2026-05-04",
            budget=2000000.0,
            raw_message="도쿄",
            **(intent_extra or {}),
        )
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        plan_events = [e for e in events if e["type"] == "plan_update"]
        assert len(plan_events) == 1
        return plan_events[0]["data"]

    def test_plan_update_has_days(self):
        data = self._get_plan_update()
        assert "days" in data
        assert len(data["days"]) == 2

    def test_plan_update_has_destination(self):
        data = self._get_plan_update()
        assert "destination" in data
        assert data["destination"] == "도쿄"

    def test_plan_update_has_start_date(self):
        data = self._get_plan_update()
        assert "start_date" in data
        assert data["start_date"] == "2026-05-01"

    def test_plan_update_has_end_date(self):
        data = self._get_plan_update()
        assert "end_date" in data
        assert data["end_date"] == "2026-05-04"

    def test_plan_update_has_budget(self):
        data = self._get_plan_update()
        assert "budget" in data
        assert data["budget"] == 2000000.0

    def test_plan_update_has_total_estimated_cost(self):
        data = self._get_plan_update()
        assert "total_estimated_cost" in data
        assert data["total_estimated_cost"] == 500.0

    def test_plan_update_budget_defaults_when_intent_has_no_budget(self):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _fake_itinerary()
        svc = _make_svc(gemini=mock_gemini)
        session = svc.create_session()
        intent = Intent(action="create_plan", destination="도쿄", budget=None, raw_message="도쿄")
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        plan_data = next(e["data"] for e in events if e["type"] == "plan_update")
        # Should always have a budget (default fallback)
        assert "budget" in plan_data
        assert plan_data["budget"] > 0


# ---------------------------------------------------------------------------
# day_update event shape (used by handleDayUpdate in chat.js)
# ---------------------------------------------------------------------------

class TestDayUpdateEventShape:
    """day_update events must carry places with estimated_cost for the Day card UI."""

    def _get_day_updates(self):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _fake_itinerary()
        svc = _make_svc(gemini=mock_gemini)
        session = svc.create_session()
        intent = Intent(
            action="create_plan", destination="도쿄",
            start_date="2026-05-01", end_date="2026-05-02",
            budget=1000.0, raw_message="도쿄",
        )
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        return [e["data"] for e in events if e["type"] == "day_update"]

    def test_day_update_has_date(self):
        updates = self._get_day_updates()
        for d in updates:
            assert "date" in d

    def test_day_update_has_places(self):
        updates = self._get_day_updates()
        for d in updates:
            assert "places" in d

    def test_day_update_places_have_estimated_cost(self):
        updates = self._get_day_updates()
        for d in updates:
            for p in d["places"]:
                assert "estimated_cost" in p

    def test_day_update_places_have_name(self):
        updates = self._get_day_updates()
        for d in updates:
            for p in d["places"]:
                assert "name" in p

    def test_day_update_count_matches_itinerary_days(self):
        updates = self._get_day_updates()
        assert len(updates) == 2


# ---------------------------------------------------------------------------
# search_results event shape (used by handleSearchResults in chat.js)
# ---------------------------------------------------------------------------

class TestSearchResultsEventShape:
    """search_results events must carry structured data for the expandable agent panel."""

    def _get_search_results(self, action, dest_key, mock_service, mock_method, fake_result):
        mock_svc_obj = MagicMock()
        getattr(mock_svc_obj, mock_method).return_value = fake_result
        kwargs = {}
        kwargs[dest_key] = mock_svc_obj
        svc = _make_svc(**kwargs)
        session = svc.create_session()
        intent = Intent(action=action, destination="도쿄", raw_message="도쿄")
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        sr = [e for e in events if e["type"] == "search_results"]
        assert len(sr) == 1
        return sr[0]["data"]

    def test_hotels_search_results_has_type_hotels(self):
        data = self._get_search_results("search_hotels", "hotel", None, "search_hotels", _fake_hotels())
        assert data["type"] == "hotels"

    def test_hotels_search_results_has_results_key(self):
        data = self._get_search_results("search_hotels", "hotel", None, "search_hotels", _fake_hotels())
        assert "results" in data

    def test_hotels_results_has_hotels_list(self):
        data = self._get_search_results("search_hotels", "hotel", None, "search_hotels", _fake_hotels())
        assert "hotels" in data["results"]
        assert len(data["results"]["hotels"]) == 2

    def test_hotels_results_each_hotel_has_name(self):
        data = self._get_search_results("search_hotels", "hotel", None, "search_hotels", _fake_hotels())
        for h in data["results"]["hotels"]:
            assert "name" in h

    def test_flights_search_results_has_type_flights(self):
        data = self._get_search_results("search_flights", "flight", None, "search_flights", _fake_flights())
        assert data["type"] == "flights"

    def test_flights_results_has_flights_list(self):
        data = self._get_search_results("search_flights", "flight", None, "search_flights", _fake_flights())
        assert "flights" in data["results"]
        assert len(data["results"]["flights"]) == 1

    def test_flights_results_each_flight_has_airline(self):
        data = self._get_search_results("search_flights", "flight", None, "search_flights", _fake_flights())
        for f in data["results"]["flights"]:
            assert "airline" in f

    def test_places_search_results_has_type_places(self):
        data = self._get_search_results("search_places", "web", None, "search_places", _fake_places())
        assert data["type"] == "places"

    def test_places_results_has_places_list(self):
        data = self._get_search_results("search_places", "web", None, "search_places", _fake_places())
        assert "places" in data["results"]
        assert len(data["results"]["places"]) == 2

    def test_places_results_each_place_has_name(self):
        data = self._get_search_results("search_places", "web", None, "search_places", _fake_places())
        for p in data["results"]["places"]:
            assert "name" in p


# ---------------------------------------------------------------------------
# agent_status result_count for expandable panel (used by handleAgentStatus)
# ---------------------------------------------------------------------------

class TestAgentStatusResultCount:
    """agent_status 'done' events must have result_count for expandable panel trigger."""

    def test_hotel_finder_done_has_result_count(self):
        mock_hotel = MagicMock()
        mock_hotel.search_hotels.return_value = _fake_hotels()
        svc = _make_svc(hotel=mock_hotel)
        session = svc.create_session()
        intent = Intent(action="search_hotels", destination="도쿄", raw_message="도쿄")
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        done = next(
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "hotel_finder"
            and e["data"]["status"] == "done"
        )
        assert "result_count" in done["data"]
        assert done["data"]["result_count"] == 2

    def test_flight_finder_done_has_result_count(self):
        mock_flight = MagicMock()
        mock_flight.search_flights.return_value = _fake_flights()
        svc = _make_svc(flight=mock_flight)
        session = svc.create_session()
        intent = Intent(action="search_flights", destination="도쿄", raw_message="도쿄")
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        done = next(
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "flight_finder"
            and e["data"]["status"] == "done"
        )
        assert "result_count" in done["data"]
        assert done["data"]["result_count"] == 1

    def test_place_scout_done_has_result_count_for_search_places(self):
        mock_web = MagicMock()
        mock_web.search_places.return_value = _fake_places()
        svc = _make_svc(web=mock_web)
        session = svc.create_session()
        intent = Intent(action="search_places", destination="도쿄", raw_message="도쿄")
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect(svc, session.session_id, "도쿄")
        done = next(
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "place_scout"
            and e["data"]["status"] == "done"
        )
        assert "result_count" in done["data"]
        assert done["data"]["result_count"] == 2
