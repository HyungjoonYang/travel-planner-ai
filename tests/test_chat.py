"""Tests for ChatService: 기본 구조 (Task #39) + 서비스 연결 (Task #41).

Done criteria:
- ChatService가 메시지를 받아 intent JSON을 반환
- 세션 생성/조회/만료 동작
- intent에 따라 GeminiService / Search 서비스 호출
- plan_update, day_update, search_results 이벤트 emit
- 테스트 통과
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
from app.chat import ChatService, Intent, SESSION_TTL_SECONDS
from app.flight_search import FlightSearchResult, FlightResult
from app.hotel_search import HotelSearchResult, HotelResult
from app.web_search import DestinationSearchResult, PlaceSearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_events(service: ChatService, session_id: str, message: str) -> list[dict]:
    """Collect all events from process_message (sync wrapper for tests)."""

    async def _run():
        events = []
        async for event in service.process_message(session_id, message):
            events.append(event)
        return events

    return asyncio.run(_run())


def _make_service_no_api() -> ChatService:
    """ChatService with no API key — intent always returns 'general'."""
    return ChatService(api_key="", ttl_seconds=SESSION_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionCreation:
    def test_create_session_returns_session(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        assert session.session_id
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.expires_at, datetime)

    def test_created_at_before_expires_at(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        assert session.expires_at > session.created_at

    def test_ttl_is_applied(self):
        svc = ChatService(api_key="", ttl_seconds=300)
        session = svc.create_session()
        delta = (session.expires_at - session.created_at).total_seconds()
        assert abs(delta - 300) < 2

    def test_each_session_has_unique_id(self):
        svc = _make_service_no_api()
        ids = {svc.create_session().session_id for _ in range(10)}
        assert len(ids) == 10


class TestSessionRetrieval:
    def test_get_session_returns_created_session(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        fetched = svc.get_session(session.session_id)
        assert fetched is not None
        assert fetched.session_id == session.session_id

    def test_get_nonexistent_session_returns_none(self):
        svc = _make_service_no_api()
        assert svc.get_session("no-such-id") is None

    def test_get_expired_session_returns_none(self):
        svc = ChatService(api_key="", ttl_seconds=0)
        session = svc.create_session()
        # Force expiry by manipulating expires_at
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert svc.get_session(session.session_id) is None

    def test_expired_session_is_removed_from_store(self):
        svc = ChatService(api_key="", ttl_seconds=0)
        session = svc.create_session()
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        svc.get_session(session.session_id)  # triggers removal
        # Calling again should still return None (not KeyError)
        assert svc.get_session(session.session_id) is None


class TestSessionExpiry:
    def test_expire_session_returns_true_when_found(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        assert svc.expire_session(session.session_id) is True

    def test_expire_session_returns_false_when_not_found(self):
        svc = _make_service_no_api()
        assert svc.expire_session("ghost-id") is False

    def test_expired_session_no_longer_retrievable(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        svc.expire_session(session.session_id)
        assert svc.get_session(session.session_id) is None


# ---------------------------------------------------------------------------
# Intent extraction
# ---------------------------------------------------------------------------

class TestIntentExtraction:
    def test_no_api_key_returns_general(self):
        svc = _make_service_no_api()
        intent = svc.extract_intent("안녕하세요")
        assert intent.action == "general"
        assert intent.raw_message == "안녕하세요"

    def test_intent_is_intent_model(self):
        svc = _make_service_no_api()
        intent = svc.extract_intent("도쿄 3박4일 여행 계획")
        assert isinstance(intent, Intent)

    def test_gemini_called_with_api_key(self):
        mock_intent = Intent(
            action="create_plan",
            destination="도쿄",
            raw_message="도쿄 3박4일 여행 계획",
        )
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = mock_intent.model_dump_json()
        mock_client.models.generate_content.return_value = mock_response

        with patch("app.chat.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            svc = ChatService(api_key="fake-key")
            intent = svc.extract_intent("도쿄 3박4일 여행 계획")

        assert intent.action == "create_plan"
        assert intent.destination == "도쿄"

    def test_gemini_failure_falls_back_to_general(self):
        with patch("app.chat.genai") as mock_genai:
            mock_genai.Client.side_effect = Exception("API error")
            svc = ChatService(api_key="fake-key")
            intent = svc.extract_intent("some message")

        assert intent.action == "general"
        assert intent.raw_message == "some message"

    def test_intent_create_plan_fields(self):
        """Intent model accepts all expected fields."""
        intent = Intent(
            action="create_plan",
            destination="파리",
            start_date="2026-05-01",
            end_date="2026-05-07",
            budget=2000000.0,
            interests="음식, 문화",
            raw_message="파리 여행",
        )
        assert intent.destination == "파리"
        assert intent.budget == 2000000.0

    def test_intent_modify_day_fields(self):
        intent = Intent(action="modify_day", day_number=2, raw_message="2일차 수정")
        assert intent.day_number == 2

    def test_intent_save_plan_action(self):
        intent = Intent(action="save_plan", raw_message="저장해줘")
        assert intent.action == "save_plan"


# ---------------------------------------------------------------------------
# process_message — event stream
# ---------------------------------------------------------------------------

class TestProcessMessage:
    def test_invalid_session_yields_error_event(self):
        svc = _make_service_no_api()
        events = _collect_events(svc, "nonexistent", "hello")
        assert len(events) == 1
        assert events[0]["type"] == "error"

    def test_coordinator_is_first_agent(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        events = _collect_events(svc, session.session_id, "안녕하세요")
        agent_events = [e for e in events if e["type"] == "agent_status"]
        assert agent_events[0]["data"]["agent"] == "coordinator"

    def test_coordinator_thinking_then_done(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        events = _collect_events(svc, session.session_id, "hello")
        coordinator_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "coordinator"
        ]
        statuses = [e["data"]["status"] for e in coordinator_events]
        assert "thinking" in statuses
        assert "done" in statuses
        assert statuses.index("thinking") < statuses.index("done")

    def test_chat_done_is_last_event(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        events = _collect_events(svc, session.session_id, "hello")
        assert events[-1]["type"] == "chat_done"

    def test_general_intent_yields_chat_chunk(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        events = _collect_events(svc, session.session_id, "hello")
        chunk_events = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunk_events) >= 1

    def test_create_plan_activates_place_scout(self):
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(action="create_plan", destination="도쿄", raw_message="도쿄")):
            events = _collect_events(svc, session.session_id, "도쿄")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "place_scout" in agent_names

    def test_create_plan_activates_budget_analyst(self):
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(action="create_plan", destination="도쿄", raw_message="도쿄")):
            events = _collect_events(svc, session.session_id, "도쿄")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "budget_analyst" in agent_names

    def test_search_hotels_activates_hotel_finder(self):
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(action="search_hotels", destination="시부야", raw_message="호텔")):
            events = _collect_events(svc, session.session_id, "호텔 추천")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "hotel_finder" in agent_names

    def test_search_flights_activates_flight_finder(self):
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(action="search_flights", destination="도쿄", raw_message="항공")):
            events = _collect_events(svc, session.session_id, "항공편 검색")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "flight_finder" in agent_names

    def test_save_plan_activates_secretary(self):
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(action="save_plan", raw_message="저장")):
            events = _collect_events(svc, session.session_id, "저장해줘")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    def test_save_plan_emits_plan_saved_event(self):
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(action="save_plan", raw_message="저장")):
            events = _collect_events(svc, session.session_id, "저장해줘")

        saved_events = [e for e in events if e["type"] == "plan_saved"]
        assert len(saved_events) == 1

    def test_message_appended_to_session_history(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "도쿄 여행")
        fetched = svc.get_session(session.session_id)
        assert len(fetched.history) == 1
        assert fetched.history[0]["content"] == "도쿄 여행"

    def test_intent_stored_in_history(self):
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "hello")
        fetched = svc.get_session(session.session_id)
        assert "intent" in fetched.history[0]
        assert "action" in fetched.history[0]["intent"]


# ---------------------------------------------------------------------------
# HTTP endpoints (via TestClient)
# ---------------------------------------------------------------------------

class TestChatSessionEndpoints:
    def test_create_session_returns_201(self, client):
        resp = client.post("/chat/sessions")
        assert resp.status_code == 201

    def test_create_session_response_shape(self, client):
        resp = client.post("/chat/sessions")
        data = resp.json()
        assert "session_id" in data
        assert "created_at" in data
        assert "expires_at" in data

    def test_get_session_returns_200(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.get(f"/chat/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == session_id

    def test_get_nonexistent_session_returns_404(self, client):
        resp = client.get("/chat/sessions/no-such-session")
        assert resp.status_code == 404

    def test_delete_session_returns_204(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.delete(f"/chat/sessions/{session_id}")
        assert resp.status_code == 204

    def test_delete_nonexistent_session_returns_404(self, client):
        resp = client.delete("/chat/sessions/ghost")
        assert resp.status_code == 404

    def test_get_deleted_session_returns_404(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.delete(f"/chat/sessions/{session_id}")
        resp = client.get(f"/chat/sessions/{session_id}")
        assert resp.status_code == 404

    def test_send_message_to_nonexistent_session_returns_404(self, client):
        resp = client.post(
            "/chat/sessions/ghost/messages",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_send_message_empty_string_returns_422(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": ""},
        )
        assert resp.status_code == 422

    def test_send_message_returns_sse_stream(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_send_message_sse_contains_agent_status(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        raw = resp.text
        # Parse SSE lines
        events = []
        for line in raw.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        types_seen = {e["type"] for e in events}
        assert "agent_status" in types_seen
        assert "chat_done" in types_seen

    def test_coordinator_first_in_sse_stream(self, client):
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        events = []
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        agent_events = [e for e in events if e["type"] == "agent_status"]
        assert agent_events[0]["data"]["agent"] == "coordinator"


# ---------------------------------------------------------------------------
# Task #41: Service handler integration
# ---------------------------------------------------------------------------

def _make_fake_itinerary() -> AIItineraryResult:
    return AIItineraryResult(
        days=[
            AIDayItinerary(
                date="2026-05-01",
                notes="Day 1",
                places=[
                    AIPlace(name="Senso-ji", category="sightseeing", estimated_cost=0.0),
                    AIPlace(name="Ramen Ichiran", category="food", estimated_cost=15.0),
                ],
            ),
            AIDayItinerary(
                date="2026-05-02",
                notes="Day 2",
                places=[
                    AIPlace(name="Shibuya Crossing", category="sightseeing", estimated_cost=0.0),
                ],
            ),
        ],
        total_estimated_cost=500.0,
    )


def _make_fake_hotel_result() -> HotelSearchResult:
    return HotelSearchResult(
        destination="도쿄",
        hotels=[
            HotelResult(name="Hotel A", price_range="$100/night", rating="4.5"),
            HotelResult(name="Hotel B", price_range="$80/night", rating="4.0"),
        ],
    )


def _make_fake_flight_result() -> FlightSearchResult:
    return FlightSearchResult(
        departure_city="Seoul",
        arrival_city="도쿄",
        flights=[
            FlightResult(airline="Korean Air", price="$300"),
        ],
    )


def _make_fake_places_result() -> DestinationSearchResult:
    return DestinationSearchResult(
        destination="도쿄",
        query="도쿄 food",
        places=[
            PlaceSearchResult(name="Tsukiji Market", category="food"),
            PlaceSearchResult(name="Harajuku", category="sightseeing"),
            PlaceSearchResult(name="Akihabara", category="shopping"),
        ],
    )


class TestServiceHandlerIntegration:
    """Verify that intent handlers call real services and emit correct events."""

    def _make_service_with_mocks(self, gemini=None, web=None, hotel=None, flight=None):
        return ChatService(
            api_key="",
            ttl_seconds=SESSION_TTL_SECONDS,
            gemini_service=gemini or MagicMock(),
            web_search_service=web or MagicMock(),
            hotel_search_service=hotel or MagicMock(),
            flight_search_service=flight or MagicMock(),
        )

    # --- create_plan → GeminiService ---

    def test_create_plan_calls_gemini_generate_itinerary(self):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_mocks(gemini=mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄",
            start_date="2026-05-01", end_date="2026-05-02", raw_message="도쿄"
        )):
            _collect_events(svc, session.session_id, "도쿄")

        mock_gemini.generate_itinerary.assert_called_once()
        call_kwargs = mock_gemini.generate_itinerary.call_args
        assert call_kwargs[0][0] == "도쿄"  # destination

    def test_create_plan_emits_plan_update_event(self):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_mocks(gemini=mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        plan_events = [e for e in events if e["type"] == "plan_update"]
        assert len(plan_events) == 1
        assert "days" in plan_events[0]["data"]

    def test_create_plan_emits_day_update_per_day(self):
        mock_gemini = MagicMock()
        itinerary = _make_fake_itinerary()
        mock_gemini.generate_itinerary.return_value = itinerary
        svc = self._make_service_with_mocks(gemini=mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        day_events = [e for e in events if e["type"] == "day_update"]
        assert len(day_events) == len(itinerary.days)

    def test_create_plan_place_scout_done_has_result_count(self):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_mocks(gemini=mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        scout_done = next(
            (e for e in events
             if e["type"] == "agent_status"
             and e["data"]["agent"] == "place_scout"
             and e["data"]["status"] == "done"),
            None,
        )
        assert scout_done is not None
        assert "result_count" in scout_done["data"]
        assert scout_done["data"]["result_count"] == 3  # 2 + 1 places

    def test_create_plan_gemini_error_emits_planner_error_status(self):
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.side_effect = RuntimeError("Gemini unavailable")
        svc = self._make_service_with_mocks(gemini=mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1
        assert error_events[0]["data"]["agent"] == "planner"

    def test_create_plan_with_default_dates_when_missing(self):
        """When start/end dates are absent, handler should still call Gemini."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_mocks(gemini=mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄",
            start_date=None, end_date=None, raw_message="도쿄"
        )):
            _collect_events(svc, session.session_id, "도쿄")

        mock_gemini.generate_itinerary.assert_called_once()

    # --- search_places → WebSearchService ---

    def test_search_places_calls_web_search_service(self):
        mock_web = MagicMock()
        mock_web.search_places.return_value = _make_fake_places_result()
        svc = self._make_service_with_mocks(web=mock_web)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_places", destination="도쿄", interests="food", raw_message="도쿄 맛집"
        )):
            _collect_events(svc, session.session_id, "도쿄 맛집")

        mock_web.search_places.assert_called_once()
        args = mock_web.search_places.call_args[0]
        assert args[0] == "도쿄"

    def test_search_places_emits_search_results_event(self):
        mock_web = MagicMock()
        mock_web.search_places.return_value = _make_fake_places_result()
        svc = self._make_service_with_mocks(web=mock_web)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_places", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        results_events = [e for e in events if e["type"] == "search_results"]
        assert len(results_events) == 1
        assert results_events[0]["data"]["type"] == "places"

    def test_search_places_place_scout_done_has_result_count(self):
        mock_web = MagicMock()
        mock_web.search_places.return_value = _make_fake_places_result()
        svc = self._make_service_with_mocks(web=mock_web)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_places", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        scout_done = next(
            (e for e in events
             if e["type"] == "agent_status"
             and e["data"]["agent"] == "place_scout"
             and e["data"]["status"] == "done"),
            None,
        )
        assert scout_done is not None
        assert scout_done["data"]["result_count"] == 3

    # --- search_hotels → HotelSearchService ---

    def test_search_hotels_calls_hotel_search_service(self):
        mock_hotel = MagicMock()
        mock_hotel.search_hotels.return_value = _make_fake_hotel_result()
        svc = self._make_service_with_mocks(hotel=mock_hotel)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_hotels", destination="도쿄", raw_message="도쿄 호텔"
        )):
            _collect_events(svc, session.session_id, "도쿄 호텔")

        mock_hotel.search_hotels.assert_called_once()
        args = mock_hotel.search_hotels.call_args[0]
        assert args[0] == "도쿄"

    def test_search_hotels_emits_search_results_event(self):
        mock_hotel = MagicMock()
        mock_hotel.search_hotels.return_value = _make_fake_hotel_result()
        svc = self._make_service_with_mocks(hotel=mock_hotel)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_hotels", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        results_events = [e for e in events if e["type"] == "search_results"]
        assert len(results_events) == 1
        assert results_events[0]["data"]["type"] == "hotels"

    def test_search_hotels_hotel_finder_done_has_result_count(self):
        mock_hotel = MagicMock()
        mock_hotel.search_hotels.return_value = _make_fake_hotel_result()
        svc = self._make_service_with_mocks(hotel=mock_hotel)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_hotels", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        finder_done = next(
            (e for e in events
             if e["type"] == "agent_status"
             and e["data"]["agent"] == "hotel_finder"
             and e["data"]["status"] == "done"),
            None,
        )
        assert finder_done is not None
        assert finder_done["data"]["result_count"] == 2

    def test_search_hotels_error_emits_hotel_finder_error_status(self):
        mock_hotel = MagicMock()
        mock_hotel.search_hotels.side_effect = RuntimeError("hotel search failed")
        svc = self._make_service_with_mocks(hotel=mock_hotel)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_hotels", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert any(e["data"]["agent"] == "hotel_finder" for e in error_events)

    # --- search_flights → FlightSearchService ---

    def test_search_flights_calls_flight_search_service(self):
        mock_flight = MagicMock()
        mock_flight.search_flights.return_value = _make_fake_flight_result()
        svc = self._make_service_with_mocks(flight=mock_flight)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_flights", destination="도쿄", raw_message="도쿄 항공"
        )):
            _collect_events(svc, session.session_id, "도쿄 항공")

        mock_flight.search_flights.assert_called_once()
        args = mock_flight.search_flights.call_args[0]
        assert args[1] == "도쿄"  # arrival_city

    def test_search_flights_emits_search_results_event(self):
        mock_flight = MagicMock()
        mock_flight.search_flights.return_value = _make_fake_flight_result()
        svc = self._make_service_with_mocks(flight=mock_flight)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_flights", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        results_events = [e for e in events if e["type"] == "search_results"]
        assert len(results_events) == 1
        assert results_events[0]["data"]["type"] == "flights"

    def test_search_flights_flight_finder_done_has_result_count(self):
        mock_flight = MagicMock()
        mock_flight.search_flights.return_value = _make_fake_flight_result()
        svc = self._make_service_with_mocks(flight=mock_flight)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_flights", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        finder_done = next(
            (e for e in events
             if e["type"] == "agent_status"
             and e["data"]["agent"] == "flight_finder"
             and e["data"]["status"] == "done"),
            None,
        )
        assert finder_done is not None
        assert finder_done["data"]["result_count"] == 1

    def test_search_flights_error_emits_flight_finder_error_status(self):
        mock_flight = MagicMock()
        mock_flight.search_flights.side_effect = RuntimeError("flight search failed")
        svc = self._make_service_with_mocks(flight=mock_flight)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="search_flights", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert any(e["data"]["agent"] == "flight_finder" for e in error_events)


# ---------------------------------------------------------------------------
# Task #46: Session state persistence — agent_states + last_plan
# ---------------------------------------------------------------------------

class TestGetSessionIncludesAgentStates:
    """GET /chat/sessions/{id} should include agent_states accumulated during processing."""

    def test_get_session_includes_agent_states_key(self, client):
        """After sending a message, GET session response has agent_states dict."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        resp = client.get(f"/chat/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_states" in data

    def test_get_session_agent_states_is_dict(self, client):
        """agent_states is a dict keyed by agent name."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        resp = client.get(f"/chat/sessions/{session_id}")
        assert isinstance(resp.json()["agent_states"], dict)

    def test_get_session_coordinator_state_stored(self, client):
        """After a message, coordinator agent state is stored in session."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        data = client.get(f"/chat/sessions/{session_id}").json()
        assert "coordinator" in data["agent_states"]

    def test_get_session_coordinator_state_is_done(self, client):
        """Coordinator ends in 'done' state after normal processing."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        data = client.get(f"/chat/sessions/{session_id}").json()
        assert data["agent_states"]["coordinator"]["status"] == "done"

    def test_get_session_includes_last_plan_key(self, client):
        """GET session response has last_plan field (None before any plan is created)."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.get(f"/chat/sessions/{session_id}")
        assert "last_plan" in resp.json()

    def test_session_stores_agent_states_via_service(self):
        """ChatSession.agent_states is updated after process_message completes."""
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "안녕")
        fetched = svc.get_session(session.session_id)
        assert hasattr(fetched, "agent_states")
        assert "coordinator" in fetched.agent_states

    def test_session_agent_states_tracks_latest_status(self):
        """agent_states stores the last emitted status (done overwrites thinking)."""
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "hello")
        fetched = svc.get_session(session.session_id)
        assert fetched.agent_states["coordinator"]["status"] == "done"

    def test_session_stores_last_plan_on_create_plan(self):
        """last_plan is populated after a create_plan intent."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = ChatService(
            api_key="",
            gemini_service=mock_gemini,
            web_search_service=MagicMock(),
            hotel_search_service=MagicMock(),
            flight_search_service=MagicMock(),
        )
        session = svc.create_session()
        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            _collect_events(svc, session.session_id, "도쿄")
        fetched = svc.get_session(session.session_id)
        assert fetched.last_plan is not None
        assert "days" in fetched.last_plan


# ---------------------------------------------------------------------------
# Task #47: modify_day intent handler
# ---------------------------------------------------------------------------

class TestModifyDay:
    """_handle_modify_day dispatched on modify_day intent; emits planner
    agent_status (thinking→working→done) + day_update event."""

    def _make_service_with_gemini(self, gemini_mock):
        return ChatService(
            api_key="",
            ttl_seconds=SESSION_TTL_SECONDS,
            gemini_service=gemini_mock,
            web_search_service=MagicMock(),
            hotel_search_service=MagicMock(),
            flight_search_service=MagicMock(),
        )

    def test_modify_day_activates_planner_agent(self):
        """modify_day intent must activate the planner agent."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="1일차 맛집 위주로 바꿔줘"
        )):
            events = _collect_events(svc, session.session_id, "1일차 맛집 위주로 바꿔줘")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "planner" in agent_names

    def test_modify_day_planner_thinking_then_working_then_done(self):
        """Planner must transition thinking → working → done."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        planner_statuses = [
            e["data"]["status"]
            for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "planner"
        ]
        assert "thinking" in planner_statuses
        assert "working" in planner_statuses
        assert "done" in planner_statuses
        assert planner_statuses.index("thinking") < planner_statuses.index("working")
        assert planner_statuses.index("working") < planner_statuses.index("done")

    def test_modify_day_emits_day_update(self):
        """modify_day must emit at least one day_update event."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="1일차 수정해줘"
        )):
            events = _collect_events(svc, session.session_id, "1일차 수정해줘")

        day_updates = [e for e in events if e["type"] == "day_update"]
        assert len(day_updates) >= 1

    def test_modify_day_update_has_date_and_places(self):
        """day_update event data must include date and places fields."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        day_update = next(e for e in events if e["type"] == "day_update")
        assert "date" in day_update["data"]
        assert "places" in day_update["data"]

    def test_modify_day_with_existing_plan_uses_refine(self):
        """When session.last_plan exists, refine_itinerary should be called."""
        mock_gemini = MagicMock()
        itinerary = _make_fake_itinerary()
        mock_gemini.refine_itinerary.return_value = itinerary
        mock_gemini.generate_itinerary.return_value = itinerary
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        # Pre-populate last_plan on the session
        session.last_plan = {
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-04",
            "budget": 2000000.0,
            "days": [d.model_dump() for d in itinerary.days],
            "total_estimated_cost": itinerary.total_estimated_cost,
        }

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="1일차 맛집 위주"
        )):
            _collect_events(svc, session.session_id, "1일차 맛집 위주")

        mock_gemini.refine_itinerary.assert_called_once()

    def test_modify_day_without_existing_plan_uses_generate(self):
        """When session.last_plan is None, generate_itinerary should be called."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        # session.last_plan is None by default

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="1일차 수정"
        )):
            _collect_events(svc, session.session_id, "1일차 수정")

        mock_gemini.generate_itinerary.assert_called_once()

    def test_modify_day_error_emits_planner_error_status(self):
        """When Gemini fails, planner agent must emit error status."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.side_effect = RuntimeError("Gemini down")
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="modify_day", day_number=1, raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        error_events = [
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "planner"
            and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1
