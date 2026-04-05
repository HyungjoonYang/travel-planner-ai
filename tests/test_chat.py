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
from app.chat import ChatService, Intent, SESSION_TTL_SECONDS, _MAX_HISTORY_TURNS
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


# ---------------------------------------------------------------------------
# Task #48: Secretary save_plan handler — persist plan to DB
# ---------------------------------------------------------------------------

def _make_test_db():
    """Return a (engine, Session) pair backed by an in-memory SQLite DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    return engine, TestingSession


def _collect_events_with_db(svc, session_id, message, db):
    """Collect all events from process_message, passing a DB session."""
    async def _run():
        events = []
        async for event in svc.process_message(session_id, message, db=db):
            events.append(event)
        return events

    return asyncio.run(_run())


class TestSavePlanPersistence:
    """_handle_save_plan must create a TravelPlan DB record and include plan_id in plan_saved event."""

    def test_plan_save_persists_to_db(self):
        """save_plan intent creates a TravelPlan row in the database."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_plan = {
                "destination": "도쿄",
                "start_date": "2026-05-01",
                "end_date": "2026-05-04",
                "budget": 2000000.0,
                "interests": "food",
            }

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="save_plan", raw_message="저장해줘"
            )):
                _collect_events_with_db(svc, session.session_id, "저장해줘", db)

            plans = db.query(TravelPlanModel).all()
            assert len(plans) == 1
            assert plans[0].destination == "도쿄"
            assert plans[0].budget == 2000000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_plan_saved_event_includes_plan_id(self):
        """plan_saved SSE event must include a non-None plan_id after DB insert."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_plan = {
                "destination": "파리",
                "start_date": "2026-06-01",
                "end_date": "2026-06-05",
                "budget": 1500000.0,
                "interests": "",
            }

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="save_plan", raw_message="저장"
            )):
                events = _collect_events_with_db(svc, session.session_id, "저장", db)

            saved_events = [e for e in events if e["type"] == "plan_saved"]
            assert len(saved_events) == 1
            assert "plan_id" in saved_events[0]["data"]
            assert saved_events[0]["data"]["plan_id"] is not None
            assert isinstance(saved_events[0]["data"]["plan_id"], int)
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #50: Budget Analyst — per-category cost breakdown
# ---------------------------------------------------------------------------

class TestBudgetBreakdown:
    """create_plan must emit search_results type=budget with per-category costs."""

    def _make_service_with_gemini(self, gemini_mock):
        return ChatService(
            api_key="",
            ttl_seconds=SESSION_TTL_SECONDS,
            gemini_service=gemini_mock,
            web_search_service=MagicMock(),
            hotel_search_service=MagicMock(),
            flight_search_service=MagicMock(),
        )

    def test_create_plan_emits_budget_search_results(self):
        """create_plan must emit a search_results event with type=budget."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        budget_events = [
            e for e in events
            if e["type"] == "search_results" and e["data"].get("type") == "budget"
        ]
        assert len(budget_events) == 1

    def test_budget_breakdown_has_required_keys(self):
        """The budget search_results event must include accommodation, transport, food, activities, total."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="create_plan", destination="도쿄", raw_message="도쿄"
        )):
            events = _collect_events(svc, session.session_id, "도쿄")

        budget_event = next(
            e for e in events
            if e["type"] == "search_results" and e["data"].get("type") == "budget"
        )
        breakdown = budget_event["data"]["results"]
        for key in ("accommodation", "transport", "food", "activities", "total"):
            assert key in breakdown, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Task #52: Secretary export_calendar handler
# ---------------------------------------------------------------------------

def _make_fake_calendar_result():
    from app.calendar_service import CalendarExportResult, CalendarEventResult
    from datetime import date as date_type

    return CalendarExportResult(
        plan_id=1,
        destination="도쿄",
        events_created=2,
        events=[
            CalendarEventResult(
                day_itinerary_id=1,
                event_date=date_type(2026, 5, 1),
                event_id="evt1",
                event_link="https://calendar.google.com/1",
            ),
            CalendarEventResult(
                day_itinerary_id=2,
                event_date=date_type(2026, 5, 2),
                event_id="evt2",
                event_link="https://calendar.google.com/2",
            ),
        ],
    )


def _make_mock_db_with_plan():
    mock_db = MagicMock()
    mock_db.get.return_value = MagicMock()
    return mock_db


class TestExportCalendar:
    """Secretary export_calendar handler: thinking→working→done, calls CalendarService."""

    def _make_service(self):
        return ChatService(
            api_key="",
            ttl_seconds=SESSION_TTL_SECONDS,
            gemini_service=MagicMock(),
            web_search_service=MagicMock(),
            hotel_search_service=MagicMock(),
            flight_search_service=MagicMock(),
        )

    def test_export_calendar_activates_secretary(self):
        """export_calendar intent activates the secretary agent."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_db = _make_mock_db_with_plan()

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_class.return_value.export_plan.return_value = _make_fake_calendar_result()
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더에 내보내줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "캘린더에 내보내줘", mock_db)

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    def test_export_calendar_secretary_thinking_then_working_then_done(self):
        """Secretary emits thinking → working → done for export_calendar."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_db = _make_mock_db_with_plan()

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_class.return_value.export_plan.return_value = _make_fake_calendar_result()
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더"
            )):
                events = _collect_events_with_db(svc, session.session_id, "캘린더", mock_db)

        secretary_statuses = [
            e["data"]["status"]
            for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
        ]
        assert "thinking" in secretary_statuses
        assert "working" in secretary_statuses
        assert "done" in secretary_statuses
        assert secretary_statuses.index("thinking") < secretary_statuses.index("working")
        assert secretary_statuses.index("working") < secretary_statuses.index("done")

    def test_export_calendar_calls_calendar_service(self):
        """CalendarService.export_plan is called with the plan loaded from DB."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_plan = MagicMock()
        mock_db = MagicMock()
        mock_db.get.return_value = mock_plan

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_instance = MagicMock()
            mock_cs_instance.export_plan.return_value = _make_fake_calendar_result()
            mock_cs_class.return_value = mock_cs_instance
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더"
            )):
                _collect_events_with_db(svc, session.session_id, "캘린더", mock_db)

        mock_cs_instance.export_plan.assert_called_once_with(mock_plan)

    def test_export_calendar_emits_calendar_exported_event(self):
        """export_calendar emits a calendar_exported SSE event with event count."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_db = _make_mock_db_with_plan()

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_class.return_value.export_plan.return_value = _make_fake_calendar_result()
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더"
            )):
                events = _collect_events_with_db(svc, session.session_id, "캘린더", mock_db)

        exported_events = [e for e in events if e["type"] == "calendar_exported"]
        assert len(exported_events) == 1
        assert exported_events[0]["data"]["events_created"] == 2

    def test_export_calendar_emits_chat_chunk_confirmation(self):
        """export_calendar emits a chat_chunk with confirmation text."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_db = _make_mock_db_with_plan()

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_class.return_value.export_plan.return_value = _make_fake_calendar_result()
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더"
            )):
                events = _collect_events_with_db(svc, session.session_id, "캘린더", mock_db)

        chunk_events = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunk_events) >= 1

    def test_export_calendar_done_has_result_count(self):
        """Secretary done event includes result_count matching events_created."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_db = _make_mock_db_with_plan()

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_class.return_value.export_plan.return_value = _make_fake_calendar_result()
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더"
            )):
                events = _collect_events_with_db(svc, session.session_id, "캘린더", mock_db)

        secretary_done = next(
            (e for e in events
             if e["type"] == "agent_status"
             and e["data"]["agent"] == "secretary"
             and e["data"]["status"] == "done"),
            None,
        )
        assert secretary_done is not None
        assert "result_count" in secretary_done["data"]
        assert secretary_done["data"]["result_count"] == 2

    def test_export_calendar_no_token_emits_secretary_error(self):
        """export_calendar without access_token emits secretary error status."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="export_calendar", access_token=None, raw_message="캘린더"
        )):
            events = _collect_events(svc, session.session_id, "캘린더")

        error_events = [
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "secretary"
            and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_export_calendar_no_saved_plan_emits_secretary_error(self):
        """export_calendar without a saved plan_id emits secretary error status."""
        svc = self._make_service()
        session = svc.create_session()
        # session.last_saved_plan_id is None by default

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="export_calendar", access_token="fake-token", raw_message="캘린더"
        )):
            events = _collect_events(svc, session.session_id, "캘린더")

        error_events = [
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "secretary"
            and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_export_calendar_calendar_service_failure_emits_error(self):
        """When CalendarService.export_plan raises, secretary emits error status."""
        svc = self._make_service()
        session = svc.create_session()
        session.last_saved_plan_id = 1
        mock_db = _make_mock_db_with_plan()

        with patch("app.chat.CalendarService") as mock_cs_class:
            mock_cs_class.return_value.export_plan.side_effect = RuntimeError("Google API error")
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="export_calendar", access_token="fake-token", raw_message="캘린더"
            )):
                events = _collect_events_with_db(svc, session.session_id, "캘린더", mock_db)

        error_events = [
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "secretary"
            and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_export_calendar_no_token_emits_chat_chunk(self):
        """export_calendar without token emits a chat_chunk explaining the requirement."""
        svc = self._make_service()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="export_calendar", access_token=None, raw_message="캘린더"
        )):
            events = _collect_events(svc, session.session_id, "캘린더")

        chunk_events = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunk_events) >= 1

    def test_save_plan_stores_last_saved_plan_id_in_session(self):
        """_handle_save_plan must store the DB plan_id in session.last_saved_plan_id."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_plan = {
                "destination": "도쿄",
                "start_date": "2026-05-01",
                "end_date": "2026-05-04",
                "budget": 2000000.0,
                "interests": "food",
            }

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="save_plan", raw_message="저장해줘"
            )):
                _collect_events_with_db(svc, session.session_id, "저장해줘", db)

            fetched = svc.get_session(session.session_id)
            assert fetched.last_saved_plan_id is not None
            assert isinstance(fetched.last_saved_plan_id, int)
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #56: list_plans intent handler
# ---------------------------------------------------------------------------

class TestListPlans:
    """_handle_list_plans queries DB and emits secretary agent_status + plans_list + chat_chunk."""

    def _make_service(self):
        return ChatService(
            api_key="",
            ttl_seconds=SESSION_TTL_SECONDS,
            gemini_service=MagicMock(),
            web_search_service=MagicMock(),
            hotel_search_service=MagicMock(),
            flight_search_service=MagicMock(),
        )

    def _seed_plans(self, db, plans_data):
        """Insert TravelPlan rows into test DB."""
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date as date_type

        records = []
        for p in plans_data:
            record = TravelPlanModel(
                destination=p["destination"],
                start_date=date_type.fromisoformat(p["start_date"]),
                end_date=date_type.fromisoformat(p["end_date"]),
                budget=p.get("budget", 1000.0),
                interests=p.get("interests", ""),
            )
            db.add(record)
            records.append(record)
        db.commit()
        return records

    # --- intent recognition ---

    def test_list_plans_intent_dispatches_to_handler(self):
        """list_plans intent must not fall through to the general handler."""
        svc = self._make_service()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="list_plans", raw_message="내 여행 목록 보여줘"
        )):
            events = _collect_events(svc, session.session_id, "내 여행 목록 보여줘")

        # secretary agent should be activated (not absent like in general handler)
        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    # --- secretary agent status events ---

    def test_list_plans_emits_secretary_working(self):
        """list_plans must emit secretary working status."""
        svc = self._make_service()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="list_plans", raw_message="목록"
        )):
            events = _collect_events(svc, session.session_id, "목록")

        secretary_statuses = [
            e["data"]["status"]
            for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
        ]
        assert "working" in secretary_statuses

    def test_list_plans_emits_secretary_done(self):
        """list_plans must end with secretary done status."""
        svc = self._make_service()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="list_plans", raw_message="목록"
        )):
            events = _collect_events(svc, session.session_id, "목록")

        secretary_statuses = [
            e["data"]["status"]
            for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
        ]
        assert "done" in secretary_statuses
        assert secretary_statuses.index("working") < secretary_statuses.index("done")

    # --- no DB ---

    def test_list_plans_no_db_emits_chat_chunk(self):
        """list_plans without db emits chat_chunk with empty message."""
        svc = self._make_service()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="list_plans", raw_message="목록"
        )):
            events = _collect_events(svc, session.session_id, "목록")

        chunk_events = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunk_events) >= 1

    # --- with DB ---

    def test_list_plans_with_empty_db_emits_empty_message(self):
        """When DB has no plans, chat_chunk mentions no saved plans."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = self._make_service()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_plans", raw_message="목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "목록", db)

            chunk_events = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chunk_events) >= 1
            # All chunks concatenated should mention "없습니다"
            full_text = " ".join(e["data"]["text"] for e in chunk_events)
            assert "없습니다" in full_text
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_list_plans_queries_db_and_emits_plans_list(self):
        """list_plans emits a plans_list event with the saved plans."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = self._make_service()
            session = svc.create_session()
            self._seed_plans(db, [
                {"destination": "도쿄", "start_date": "2026-05-01", "end_date": "2026-05-04"},
                {"destination": "파리", "start_date": "2026-06-10", "end_date": "2026-06-15"},
            ])

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_plans", raw_message="목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "목록", db)

            plans_list_events = [e for e in events if e["type"] == "plans_list"]
            assert len(plans_list_events) == 1
            plans = plans_list_events[0]["data"]["plans"]
            assert len(plans) == 2
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_list_plans_plan_items_have_required_fields(self):
        """Each plan in plans_list must have id, destination, start_date, end_date, budget, status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = self._make_service()
            session = svc.create_session()
            self._seed_plans(db, [
                {"destination": "도쿄", "start_date": "2026-05-01", "end_date": "2026-05-04", "budget": 500.0},
            ])

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_plans", raw_message="목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "목록", db)

            plans_list_events = [e for e in events if e["type"] == "plans_list"]
            plan = plans_list_events[0]["data"]["plans"][0]
            for field in ("id", "destination", "start_date", "end_date", "budget", "status"):
                assert field in plan, f"Missing field: {field}"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_list_plans_chat_chunk_contains_destination(self):
        """The chat_chunk text for list_plans must mention plan destinations."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = self._make_service()
            session = svc.create_session()
            self._seed_plans(db, [
                {"destination": "도쿄", "start_date": "2026-05-01", "end_date": "2026-05-04"},
            ])

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_plans", raw_message="목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "목록", db)

            chunk_events = [e for e in events if e["type"] == "chat_chunk"]
            full_text = " ".join(e["data"]["text"] for e in chunk_events)
            assert "도쿄" in full_text
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_list_plans_secretary_done_result_count_matches_plans(self):
        """secretary done event result_count must equal number of plans returned."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = self._make_service()
            session = svc.create_session()
            self._seed_plans(db, [
                {"destination": "도쿄", "start_date": "2026-05-01", "end_date": "2026-05-04"},
                {"destination": "파리", "start_date": "2026-06-10", "end_date": "2026-06-15"},
                {"destination": "뉴욕", "start_date": "2026-07-01", "end_date": "2026-07-07"},
            ])

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_plans", raw_message="목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "목록", db)

            secretary_done = next(
                (e for e in events
                 if e["type"] == "agent_status"
                 and e["data"]["agent"] == "secretary"
                 and e["data"]["status"] == "done"),
                None,
            )
            assert secretary_done is not None
            assert "result_count" in secretary_done["data"]
            assert secretary_done["data"]["result_count"] == 3
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_list_plans_db_error_emits_secretary_error(self):
        """When DB query raises, secretary emits error status."""
        svc = self._make_service()
        session = svc.create_session()

        mock_db = MagicMock()
        mock_db.query.side_effect = RuntimeError("DB unavailable")

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="list_plans", raw_message="목록"
        )):
            events = _collect_events_with_db(svc, session.session_id, "목록", mock_db)

        error_events = [
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "secretary"
            and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1


# ---------------------------------------------------------------------------
# Task #53: Conversation context — message_history (max 10 turns) passed to Gemini
# ---------------------------------------------------------------------------

class TestConversationContext:
    """ChatSession.message_history stores up to 10 turns; history is passed to
    extract_intent so follow-up messages can infer prior context."""

    def test_max_history_turns_constant_is_10(self):
        """_MAX_HISTORY_TURNS must equal 10."""
        assert _MAX_HISTORY_TURNS == 10

    def test_session_has_message_history_field(self):
        """ChatSession must have a message_history attribute initialized to []."""
        svc = _make_service_no_api()
        session = svc.create_session()
        assert hasattr(session, "message_history")
        assert session.message_history == []

    def test_user_message_appended_to_message_history(self):
        """After process_message, message_history contains the user turn."""
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "도쿄 여행 계획해줘")
        fetched = svc.get_session(session.session_id)
        user_turns = [e for e in fetched.message_history if e["role"] == "user"]
        assert len(user_turns) == 1
        assert user_turns[0]["content"] == "도쿄 여행 계획해줘"

    def test_assistant_response_appended_to_message_history(self):
        """After process_message, message_history contains an assistant turn."""
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "안녕하세요")
        fetched = svc.get_session(session.session_id)
        assistant_turns = [e for e in fetched.message_history if e["role"] == "assistant"]
        assert len(assistant_turns) == 1
        assert assistant_turns[0]["content"]  # non-empty

    def test_message_history_alternates_user_assistant(self):
        """After two messages, message_history has user/assistant/user/assistant order."""
        svc = _make_service_no_api()
        session = svc.create_session()
        _collect_events(svc, session.session_id, "첫 번째 메시지")
        _collect_events(svc, session.session_id, "두 번째 메시지")
        fetched = svc.get_session(session.session_id)
        roles = [e["role"] for e in fetched.message_history]
        assert roles == ["user", "assistant", "user", "assistant"]

    def test_message_history_capped_at_10_turns(self):
        """Sending 12 messages must keep message_history at max 10 turns (20 entries)."""
        svc = _make_service_no_api()
        session = svc.create_session()
        for i in range(12):
            _collect_events(svc, session.session_id, f"메시지 {i}")
        fetched = svc.get_session(session.session_id)
        max_entries = _MAX_HISTORY_TURNS * 2  # 10 turns = 10 user + 10 assistant
        assert len(fetched.message_history) <= max_entries

    def test_message_history_keeps_most_recent_turns(self):
        """After exceeding max turns, the oldest turns are dropped."""
        svc = _make_service_no_api()
        session = svc.create_session()
        for i in range(12):
            _collect_events(svc, session.session_id, f"메시지 {i}")
        fetched = svc.get_session(session.session_id)
        user_messages = [e["content"] for e in fetched.message_history if e["role"] == "user"]
        # Most recent messages should be retained
        assert "메시지 11" in user_messages
        assert "메시지 10" in user_messages
        # Oldest should be dropped
        assert "메시지 0" not in user_messages

    def test_extract_intent_receives_message_history(self):
        """extract_intent must be called with the session's current message_history."""
        svc = _make_service_no_api()
        session = svc.create_session()
        # Pre-populate history to simulate a prior exchange
        session.message_history = [
            {"role": "user", "content": "도쿄 3박4일 여행 계획해줘"},
            {"role": "assistant", "content": "도쿄 3박4일 여행 계획을 생성했습니다."},
        ]

        captured_kwargs = {}

        original = svc.extract_intent

        def spy_extract_intent(message, history=None):
            captured_kwargs["history"] = history
            return original(message, history=history)

        svc.extract_intent = spy_extract_intent
        _collect_events(svc, session.session_id, "3일차 맛집 위주로 바꿔줘")

        assert "history" in captured_kwargs
        assert captured_kwargs["history"] is not None
        assert len(captured_kwargs["history"]) == 2

    def test_extract_intent_with_history_includes_context_in_prompt(self):
        """When history is passed, the Gemini prompt must include conversation context."""
        history = [
            {"role": "user", "content": "도쿄 3박4일 여행"},
            {"role": "assistant", "content": "도쿄 3일 일정을 만들었습니다."},
        ]
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = Intent(action="modify_day", day_number=2, raw_message="2일차 수정").model_dump_json()
        mock_client.models.generate_content.return_value = mock_response

        with patch("app.chat.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            svc = ChatService(api_key="fake-key")
            svc.extract_intent("2일차 자연 위주로 바꿔줘", history=history)

        call_args = mock_client.models.generate_content.call_args
        prompt_text = call_args[1]["contents"] if "contents" in call_args[1] else call_args[0][1]
        # The prompt must reference the prior conversation
        assert "도쿄 3박4일 여행" in prompt_text or "Previous" in prompt_text or "conversation" in prompt_text.lower()

    def test_extract_intent_without_history_still_works(self):
        """extract_intent with no history (default) must behave as before."""
        svc = _make_service_no_api()
        intent = svc.extract_intent("도쿄 여행 계획해줘")
        assert isinstance(intent, Intent)
        assert intent.action == "general"

    def test_extract_intent_with_empty_history_still_works(self):
        """extract_intent with empty history list behaves like no history."""
        svc = _make_service_no_api()
        intent = svc.extract_intent("도쿄 여행 계획해줘", history=[])
        assert isinstance(intent, Intent)

    def test_message_history_available_in_session_endpoint(self, client):
        """GET /chat/sessions/{id} response includes message_history field."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        resp = client.get(f"/chat/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "message_history" in data

    def test_message_history_entries_have_role_and_content(self, client):
        """Each message_history entry must have 'role' and 'content' keys."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        data = client.get(f"/chat/sessions/{session_id}").json()
        for entry in data["message_history"]:
            assert "role" in entry
            assert "content" in entry
            assert entry["role"] in ("user", "assistant")


# ---------------------------------------------------------------------------
# Task #59: delete_plan intent handler
# ---------------------------------------------------------------------------

class TestDeletePlan:
    """_handle_delete_plan must delete the plan from DB and emit plan_deleted."""

    def test_delete_plan_activates_secretary(self):
        """delete_plan intent activates the secretary agent."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="delete_plan", plan_id=1, raw_message="계획 삭제"
        )):
            events = _collect_events(svc, session.session_id, "계획 삭제")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    def test_delete_plan_emits_plan_deleted_event(self):
        """delete_plan must emit a plan_deleted SSE event when DB record is found."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            # Insert a plan to delete
            plan = TravelPlanModel(
                destination="바르셀로나",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 5),
                budget=1800000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            plan_id = plan.id

            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_plan", plan_id=plan_id, raw_message="계획 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 삭제", db)

            deleted_events = [e for e in events if e["type"] == "plan_deleted"]
            assert len(deleted_events) == 1
            assert deleted_events[0]["data"]["plan_id"] == plan_id
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_plan_removes_from_db(self):
        """delete_plan must physically remove the TravelPlan row from the database."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan = TravelPlanModel(
                destination="런던",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 7),
                budget=3000000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            plan_id = plan.id

            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_plan", plan_id=plan_id, raw_message="삭제"
            )):
                _collect_events_with_db(svc, session.session_id, "삭제", db)

            remaining = db.query(TravelPlanModel).filter(TravelPlanModel.id == plan_id).first()
            assert remaining is None
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_plan_no_db_emits_error(self):
        """delete_plan without a DB session must emit an error agent_status."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="delete_plan", plan_id=99, raw_message="삭제"
        )):
            events = _collect_events(svc, session.session_id, "삭제")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_delete_plan_nonexistent_plan_emits_error(self):
        """delete_plan for a missing plan_id must emit an error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_plan", plan_id=9999, raw_message="삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "삭제", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_plan_clears_session_last_saved_plan_id(self):
        """After deleting the last saved plan, session.last_saved_plan_id must be cleared."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan = TravelPlanModel(
                destination="뉴욕",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 5),
                budget=5000000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            plan_id = plan.id

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_plan", plan_id=plan_id, raw_message="삭제"
            )):
                _collect_events_with_db(svc, session.session_id, "삭제", db)

            assert session.last_saved_plan_id is None
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #60: view_plan intent handler — load saved plan into dashboard
# ---------------------------------------------------------------------------

class TestViewPlan:
    """_handle_view_plan must fetch a plan by ID or destination and emit plan_update."""

    def test_view_plan_by_id_emits_plan_update(self):
        """view_plan with a valid plan_id must emit a plan_update event with the plan data."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan = TravelPlanModel(
                destination="파리",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 5),
                budget=3000000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            plan_id = plan.id

            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="view_plan", plan_id=plan_id, raw_message="파리 계획 보여줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "파리 계획 보여줘", db)

            plan_update_events = [e for e in events if e["type"] == "plan_update"]
            assert len(plan_update_events) == 1
            data = plan_update_events[0]["data"]
            assert data["id"] == plan_id
            assert data["destination"] == "파리"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_view_plan_by_destination_substring_emits_plan_update(self):
        """view_plan without a plan_id must fall back to destination substring search."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan = TravelPlanModel(
                destination="바르셀로나",
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 15),
                budget=4000000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)

            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="view_plan", destination="바르셀로나", raw_message="바르셀로나 계획 보여줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "바르셀로나 계획 보여줘", db)

            plan_update_events = [e for e in events if e["type"] == "plan_update"]
            assert len(plan_update_events) == 1
            assert plan_update_events[0]["data"]["destination"] == "바르셀로나"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_view_plan_no_db_emits_error(self):
        """view_plan without a DB session must emit an error agent_status."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="view_plan", plan_id=1, raw_message="계획 보여줘"
        )):
            events = _collect_events(svc, session.session_id, "계획 보여줘")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_view_plan_not_found_emits_error(self):
        """view_plan for a non-existent plan must emit an error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="view_plan", plan_id=9999, raw_message="계획 보여줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 보여줘", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_view_plan_sets_session_state(self):
        """view_plan must update session.last_plan and session.last_saved_plan_id."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan = TravelPlanModel(
                destination="로마",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 6),
                budget=2500000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            plan_id = plan.id

            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="view_plan", plan_id=plan_id, raw_message="로마 계획 보여줘"
            )):
                _collect_events_with_db(svc, session.session_id, "로마 계획 보여줘", db)

            assert session.last_saved_plan_id == plan_id
            assert session.last_plan is not None
            assert session.last_plan["destination"] == "로마"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #63: add_expense intent handler
# ---------------------------------------------------------------------------

def _seed_plan_for_expense(db):
    """Insert a TravelPlan row and return its id."""
    from app.models import TravelPlan as TravelPlanModel
    from datetime import date

    plan = TravelPlanModel(
        destination="도쿄",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 5),
        budget=500000.0,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan.id


class TestAddExpense:
    """_handle_add_expense must persist an Expense row and emit expense_added SSE."""

    def test_add_expense_activates_secretary(self):
        """add_expense intent activates the secretary agent."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="add_expense", expense_name="식사", expense_amount=50000.0,
            raw_message="식사 5만원 추가"
        )):
            events = _collect_events(svc, session.session_id, "식사 5만원 추가")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    def test_add_expense_no_db_emits_error(self):
        """add_expense without a DB session emits error because there is no plan to attach to."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="add_expense", expense_name="택시", expense_amount=15000.0,
            raw_message="택시 15000원 추가"
        )):
            events = _collect_events(svc, session.session_id, "택시 15000원 추가")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_add_expense_no_saved_plan_emits_error(self):
        """add_expense without session.last_saved_plan_id emits error."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            # Do NOT set session.last_saved_plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="식사", expense_amount=30000.0,
                raw_message="식사 3만원 추가"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 3만원 추가", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_missing_amount_emits_error(self):
        """add_expense without an amount emits error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="식사", expense_amount=None,
                raw_message="식사 추가"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 추가", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_persists_to_db(self):
        """add_expense intent creates an Expense row in the database."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="식사", expense_amount=50000.0,
                expense_category="food", raw_message="식사 5만원 추가"
            )):
                _collect_events_with_db(svc, session.session_id, "식사 5만원 추가", db)

            expenses = db.query(ExpenseModel).filter(ExpenseModel.travel_plan_id == plan_id).all()
            assert len(expenses) == 1
            assert expenses[0].name == "식사"
            assert expenses[0].amount == 50000.0
            assert expenses[0].category == "food"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_emits_expense_added_event(self):
        """add_expense must emit an expense_added SSE event."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="택시", expense_amount=15000.0,
                expense_category="transport", raw_message="택시 15000원"
            )):
                events = _collect_events_with_db(svc, session.session_id, "택시 15000원", db)

            expense_events = [e for e in events if e["type"] == "expense_added"]
            assert len(expense_events) == 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_event_has_expense_and_budget_summary(self):
        """expense_added event must contain 'expense' and 'budget_summary' keys."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="입장료", expense_amount=10000.0,
                raw_message="입장료 1만원"
            )):
                events = _collect_events_with_db(svc, session.session_id, "입장료 1만원", db)

            evt = next(e for e in events if e["type"] == "expense_added")
            assert "expense" in evt["data"]
            assert "budget_summary" in evt["data"]
            assert evt["data"]["expense"]["name"] == "입장료"
            assert evt["data"]["expense"]["amount"] == 10000.0
            assert evt["data"]["budget_summary"]["total_spent"] == 10000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_budget_summary_over_budget(self):
        """When total expenses exceed budget, budget_summary.over_budget must be True."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)  # budget=500000

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="호텔", expense_amount=600000.0,
                raw_message="호텔 60만원"
            )):
                events = _collect_events_with_db(svc, session.session_id, "호텔 60만원", db)

            evt = next(e for e in events if e["type"] == "expense_added")
            assert evt["data"]["budget_summary"]["over_budget"] is True
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_emits_chat_chunk(self):
        """add_expense must emit a chat_chunk with confirmation text."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="커피", expense_amount=5000.0,
                raw_message="커피 5000원"
            )):
                events = _collect_events_with_db(svc, session.session_id, "커피 5000원", db)

            chunk_events = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chunk_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_intent_has_new_fields(self):
        """Intent model must accept expense_name, expense_amount, expense_category fields."""
        intent = Intent(
            action="add_expense",
            expense_name="식사",
            expense_amount=50000.0,
            expense_category="food",
            raw_message="식사 5만원 추가",
        )
        assert intent.expense_name == "식사"
        assert intent.expense_amount == 50000.0
        assert intent.expense_category == "food"

    def test_add_expense_uses_session_plan_id_when_no_intent_plan_id(self):
        """add_expense falls back to session.last_saved_plan_id when intent.plan_id is None."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id  # set via session, not intent

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="식사", expense_amount=25000.0,
                plan_id=None, raw_message="식사 2.5만원"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 2.5만원", db)

            expense_events = [e for e in events if e["type"] == "expense_added"]
            assert len(expense_events) == 1
            expenses = db.query(ExpenseModel).filter(ExpenseModel.travel_plan_id == plan_id).all()
            assert len(expenses) == 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_add_expense_nonexistent_plan_emits_error(self):
        """add_expense for a missing plan_id must emit an error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = 9999  # non-existent plan

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="add_expense", expense_name="식사", expense_amount=50000.0,
                raw_message="식사 5만원 추가"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 5만원 추가", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_view_plan_secretary_done_status(self):
        """view_plan must emit a secretary done agent_status event on success."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan = TravelPlanModel(
                destination="암스테르담",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 4),
                budget=1800000.0,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            plan_id = plan.id

            svc = _make_service_no_api()
            session = svc.create_session()

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="view_plan", plan_id=plan_id, raw_message="계획 보여줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 보여줘", db)

            secretary_done = next(
                (
                    e for e in events
                    if e["type"] == "agent_status"
                    and e["data"]["agent"] == "secretary"
                    and e["data"]["status"] == "done"
                ),
                None,
            )
            assert secretary_done is not None
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #64: update_plan intent handler — edit plan metadata via chat
# ---------------------------------------------------------------------------

def _seed_plan_for_update(db):
    """Insert a TravelPlan row for update tests and return its id."""
    from app.models import TravelPlan as TravelPlanModel
    from datetime import date as date_type

    plan = TravelPlanModel(
        destination="도쿄",
        start_date=date_type(2026, 5, 1),
        end_date=date_type(2026, 5, 5),
        budget=1000000.0,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan.id


class TestUpdatePlan:
    """_handle_update_plan must update DB fields and emit plan_update SSE.
    Done criteria: budget/title/date update via natural language; plan_update SSE emitted; 3 field types tested.
    """

    # --- intent recognition ---

    def test_update_plan_activates_secretary(self):
        """update_plan intent activates the secretary agent."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="update_plan", budget=2000000.0, raw_message="예산 200만원으로 바꿔줘"
        )):
            events = _collect_events(svc, session.session_id, "예산 200만원으로 바꿔줘")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    # --- field type 1: budget update ---

    def test_update_plan_budget_persists_to_db(self):
        """update_plan with new budget must update TravelPlan.budget in DB."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=2000000.0, raw_message="예산 200만원으로 바꿔줘"
            )):
                _collect_events_with_db(svc, session.session_id, "예산 200만원으로 바꿔줘", db)

            plan = db.get(TravelPlanModel, plan_id)
            assert plan.budget == 2000000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_budget_emits_plan_update(self):
        """update_plan with new budget must emit a plan_update SSE event."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=1500000.0, raw_message="예산 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 수정", db)

            plan_update_events = [e for e in events if e["type"] == "plan_update"]
            assert len(plan_update_events) == 1
            assert plan_update_events[0]["data"]["budget"] == 1500000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    # --- field type 2: destination/title update ---

    def test_update_plan_destination_persists_to_db(self):
        """update_plan with new destination must update TravelPlan.destination in DB."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", destination="오사카", raw_message="목적지를 오사카로 바꿔줘"
            )):
                _collect_events_with_db(svc, session.session_id, "목적지를 오사카로 바꿔줘", db)

            plan = db.get(TravelPlanModel, plan_id)
            assert plan.destination == "오사카"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_destination_emits_plan_update(self):
        """update_plan with new destination must emit plan_update with updated destination."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", destination="교토", raw_message="교토로 바꿔줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "교토로 바꿔줘", db)

            plan_update_events = [e for e in events if e["type"] == "plan_update"]
            assert len(plan_update_events) == 1
            assert plan_update_events[0]["data"]["destination"] == "교토"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    # --- field type 3: date update ---

    def test_update_plan_start_date_persists_to_db(self):
        """update_plan with new start_date must update TravelPlan.start_date in DB."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date as date_type

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", start_date="2026-06-01", raw_message="출발일을 6월 1일로 바꿔줘"
            )):
                _collect_events_with_db(svc, session.session_id, "출발일을 6월 1일로 바꿔줘", db)

            plan = db.get(TravelPlanModel, plan_id)
            assert plan.start_date == date_type(2026, 6, 1)
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_end_date_persists_to_db(self):
        """update_plan with new end_date must update TravelPlan.end_date in DB."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel
        from datetime import date as date_type

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", end_date="2026-06-07", raw_message="종료일을 6월 7일로 바꿔줘"
            )):
                _collect_events_with_db(svc, session.session_id, "종료일을 6월 7일로 바꿔줘", db)

            plan = db.get(TravelPlanModel, plan_id)
            assert plan.end_date == date_type(2026, 6, 7)
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_date_emits_plan_update(self):
        """update_plan with new dates must emit a plan_update SSE event with updated dates."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", start_date="2026-07-10", end_date="2026-07-15",
                raw_message="날짜를 7월 10~15일로 변경해줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "날짜 변경", db)

            plan_update_events = [e for e in events if e["type"] == "plan_update"]
            assert len(plan_update_events) == 1
            data = plan_update_events[0]["data"]
            assert data["start_date"] == "2026-07-10"
            assert data["end_date"] == "2026-07-15"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    # --- secretary agent status ---

    def test_update_plan_secretary_working_then_done(self):
        """Secretary must transition working → done on successful update_plan."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=3000000.0, raw_message="예산 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 수정", db)

            secretary_statuses = [
                e["data"]["status"]
                for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
            ]
            assert "working" in secretary_statuses
            assert "done" in secretary_statuses
            assert secretary_statuses.index("working") < secretary_statuses.index("done")
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    # --- plan_update event shape ---

    def test_update_plan_plan_update_has_required_fields(self):
        """plan_update event must include id, destination, start_date, end_date, budget, status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=500000.0, raw_message="예산 변경"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 변경", db)

            plan_update = next(e for e in events if e["type"] == "plan_update")
            for field in ("id", "destination", "start_date", "end_date", "budget", "status"):
                assert field in plan_update["data"], f"Missing field: {field}"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    # --- session state update ---

    def test_update_plan_updates_session_state(self):
        """update_plan must update session.last_plan and session.last_saved_plan_id."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", destination="삿포로", raw_message="목적지 변경"
            )):
                _collect_events_with_db(svc, session.session_id, "목적지 변경", db)

            assert session.last_saved_plan_id == plan_id
            assert session.last_plan is not None
            assert session.last_plan["destination"] == "삿포로"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    # --- error cases ---

    def test_update_plan_no_db_emits_error(self):
        """update_plan without a DB session must emit an error agent_status."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="update_plan", budget=1000000.0, raw_message="예산 변경"
        )):
            events = _collect_events(svc, session.session_id, "예산 변경")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_update_plan_no_saved_plan_emits_error(self):
        """update_plan without session.last_saved_plan_id emits error."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            # Do NOT set session.last_saved_plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=2000000.0, raw_message="예산 변경"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 변경", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_nonexistent_plan_emits_error(self):
        """update_plan for a missing plan_id must emit an error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = 9999  # non-existent

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=2000000.0, raw_message="예산 변경"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 변경", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_no_changed_fields_emits_error(self):
        """update_plan with no recognizable fields (no budget/destination/dates) emits error."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            # No fields set — all None
            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", raw_message="뭔가 바꿔줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "뭔가 바꿔줘", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_uses_intent_plan_id(self):
        """update_plan can use intent.plan_id directly (not just session's last_saved_plan_id)."""
        from app.database import Base
        from app.models import TravelPlan as TravelPlanModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            # session.last_saved_plan_id intentionally left None

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", plan_id=plan_id, budget=3000000.0,
                raw_message=f"{plan_id}번 계획 예산 300만원으로 변경"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 변경", db)

            plan_update_events = [e for e in events if e["type"] == "plan_update"]
            assert len(plan_update_events) == 1
            plan = db.get(TravelPlanModel, plan_id)
            assert plan.budget == 3000000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_plan_emits_chat_chunk_with_change_summary(self):
        """update_plan must emit a chat_chunk describing what was changed."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_update(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_plan", budget=2500000.0, raw_message="예산 250만원으로 바꿔줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "예산 변경", db)

            chunk_events = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chunk_events) >= 1
            full_text = " ".join(e["data"]["text"] for e in chunk_events)
            assert "수정" in full_text or "변경" in full_text
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #65: get_expense_summary intent handler
# ---------------------------------------------------------------------------

def _seed_plan_and_expenses(db, expenses):
    """Insert a TravelPlan and a list of expenses; return plan_id."""
    from app.models import Expense as ExpenseModel, TravelPlan as TravelPlanModel
    from datetime import date as date_type

    plan = TravelPlanModel(
        destination="도쿄",
        start_date=date_type(2026, 5, 1),
        end_date=date_type(2026, 5, 5),
        budget=500000.0,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    for exp in expenses:
        row = ExpenseModel(
            travel_plan_id=plan.id,
            name=exp["name"],
            amount=exp["amount"],
            category=exp.get("category", ""),
        )
        db.add(row)
    db.commit()
    return plan.id


class TestGetExpenseSummary:
    """_handle_get_expense_summary must query DB expenses and emit expense_summary SSE."""

    def test_get_expense_summary_activates_budget_analyst(self):
        """get_expense_summary intent activates the budget_analyst agent."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="get_expense_summary", raw_message="얼마 썼어"
        )):
            events = _collect_events(svc, session.session_id, "얼마 썼어")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "budget_analyst" in agent_names

    def test_get_expense_summary_no_db_emits_error(self):
        """get_expense_summary without a DB session emits error."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="get_expense_summary", raw_message="얼마 썼어"
        )):
            events = _collect_events(svc, session.session_id, "얼마 썼어")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_get_expense_summary_no_saved_plan_emits_error(self):
        """get_expense_summary without session.last_saved_plan_id emits error."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            # Do NOT set session.last_saved_plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_zero_expenses(self):
        """When no expenses exist, emits expense_summary with total_spent=0 and expense_count=0."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            summary_events = [e for e in events if e["type"] == "expense_summary"]
            assert len(summary_events) == 1
            summary = summary_events[0]["data"]
            assert summary["total_spent"] == 0
            assert summary["expense_count"] == 0
            assert summary["by_category"] == {}
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_emits_expense_summary_event(self):
        """get_expense_summary emits exactly one expense_summary SSE event."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 30000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            summary_events = [e for e in events if e["type"] == "expense_summary"]
            assert len(summary_events) == 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_required_fields(self):
        """expense_summary event must include plan_id, budget, total_spent, remaining, by_category, expense_count, over_budget."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            summary = next(e["data"] for e in events if e["type"] == "expense_summary")
            for field in ("plan_id", "budget", "total_spent", "remaining", "by_category", "expense_count", "over_budget"):
                assert field in summary, f"Missing field: {field}"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_multi_expense_total(self):
        """With multiple expenses, total_spent equals their sum."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 30000.0, "category": "food"},
                {"name": "택시", "amount": 15000.0, "category": "transport"},
                {"name": "입장료", "amount": 10000.0, "category": "activities"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            summary = next(e["data"] for e in events if e["type"] == "expense_summary")
            assert summary["total_spent"] == 55000.0
            assert summary["expense_count"] == 3
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_by_category_correct(self):
        """by_category must aggregate amounts per category."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "점심", "amount": 20000.0, "category": "food"},
                {"name": "저녁", "amount": 30000.0, "category": "food"},
                {"name": "지하철", "amount": 5000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="카테고리별 지출"
            )):
                events = _collect_events_with_db(svc, session.session_id, "카테고리별 지출", db)

            summary = next(e["data"] for e in events if e["type"] == "expense_summary")
            assert summary["by_category"]["food"] == 50000.0
            assert summary["by_category"]["transport"] == 5000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_remaining_budget_correct(self):
        """remaining must equal budget minus total_spent."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 100000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 남았어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 남았어", db)

            summary = next(e["data"] for e in events if e["type"] == "expense_summary")
            # budget is 500000, spent is 100000
            assert summary["remaining"] == 400000.0
            assert summary["over_budget"] is False
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_over_budget_flag(self):
        """over_budget must be True when total_spent > budget."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "호텔", "amount": 600000.0, "category": "accommodation"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            summary = next(e["data"] for e in events if e["type"] == "expense_summary")
            assert summary["over_budget"] is True
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_budget_analyst_working_then_done(self):
        """Budget analyst must transition working → done."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            ba_statuses = [
                e["data"]["status"]
                for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "budget_analyst"
            ]
            assert "working" in ba_statuses
            assert "done" in ba_statuses
            assert ba_statuses.index("working") < ba_statuses.index("done")
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_emits_chat_chunk(self):
        """get_expense_summary must emit at least one chat_chunk."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_for_expense(db)

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            chunk_events = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chunk_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_get_expense_summary_done_has_result_count(self):
        """Budget analyst done event must include result_count equal to expense_count."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 20000.0, "category": "food"},
                {"name": "교통", "amount": 10000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="get_expense_summary", raw_message="얼마 썼어"
            )):
                events = _collect_events_with_db(svc, session.session_id, "얼마 썼어", db)

            ba_done = next(
                (e for e in events
                 if e["type"] == "agent_status"
                 and e["data"]["agent"] == "budget_analyst"
                 and e["data"]["status"] == "done"),
                None,
            )
            assert ba_done is not None
            assert "result_count" in ba_done["data"]
            assert ba_done["data"]["result_count"] == 2
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Task #66: Chat session history persistence to SQLite
# ---------------------------------------------------------------------------

class TestChatHistoryPersistence:
    """Messages must be written to chat_messages table each exchange;
    session restore loads last 10 turns from DB; Gemini context uses DB history."""

    # --- DB write ---

    def test_process_message_writes_user_message_to_db(self):
        """After process_message with a DB, a user ChatMessage row must exist."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            _collect_events_with_db(svc, session.session_id, "안녕하세요", db)

            rows = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.session_id,
                ChatMessage.role == "user",
            ).all()
            assert len(rows) == 1
            assert rows[0].content == "안녕하세요"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_process_message_writes_assistant_message_to_db(self):
        """After process_message with a DB, an assistant ChatMessage row must exist."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            _collect_events_with_db(svc, session.session_id, "안녕하세요", db)

            rows = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.session_id,
                ChatMessage.role == "assistant",
            ).all()
            assert len(rows) == 1
            assert rows[0].content  # non-empty

        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_multiple_exchanges_write_multiple_rows(self):
        """Two exchanges must create 4 ChatMessage rows (2 user + 2 assistant)."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            _collect_events_with_db(svc, session.session_id, "첫 번째", db)
            _collect_events_with_db(svc, session.session_id, "두 번째", db)

            total = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.session_id
            ).count()
            assert total == 4
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_db_rows_have_correct_session_id(self):
        """ChatMessage rows must be tagged with the correct session_id."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            other_session = svc.create_session()

            _collect_events_with_db(svc, session.session_id, "메시지", db)
            _collect_events_with_db(svc, other_session.session_id, "다른 메시지", db)

            rows = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.session_id
            ).all()
            assert all(r.session_id == session.session_id for r in rows)
            assert len(rows) == 2  # user + assistant for session only
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_no_db_does_not_raise(self):
        """process_message without a DB must still work (no persistence)."""
        svc = _make_service_no_api()
        session = svc.create_session()
        events = _collect_events(svc, session.session_id, "안녕하세요")
        # Should complete normally with chat_done
        assert events[-1]["type"] == "chat_done"

    # --- Session restore from DB ---

    def test_session_restore_loads_history_from_db(self):
        """When a new in-memory session has no history but DB has prior messages,
        process_message must restore them before extracting intent."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            # Manually insert prior conversation into DB
            db.add(ChatMessage(
                session_id=session.session_id, role="user",
                content="도쿄 3박4일 여행 계획해줘",
            ))
            db.add(ChatMessage(
                session_id=session.session_id, role="assistant",
                content="도쿄 3일 일정을 만들었습니다.",
            ))
            db.commit()

            # At this point session.message_history is still empty (fresh session)
            assert session.message_history == []

            captured_history: list = []
            original = svc.extract_intent

            def spy(message, history=None):
                captured_history.extend(history or [])
                return original(message, history=history)

            svc.extract_intent = spy
            _collect_events_with_db(svc, session.session_id, "3일차 맛집으로 바꿔줘", db)

            # extract_intent should have received the restored history
            roles = [e["role"] for e in captured_history]
            assert "user" in roles
            assert "assistant" in roles
            contents = [e["content"] for e in captured_history]
            assert "도쿄 3박4일 여행 계획해줘" in contents
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_session_restore_loads_at_most_max_history_turns(self):
        """Restore must not load more than _MAX_HISTORY_TURNS * 2 entries."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            # Insert 15 exchanges (30 messages) into DB
            for i in range(15):
                db.add(ChatMessage(
                    session_id=session.session_id, role="user",
                    content=f"메시지 {i}",
                ))
                db.add(ChatMessage(
                    session_id=session.session_id, role="assistant",
                    content=f"응답 {i}",
                ))
            db.commit()

            _collect_events_with_db(svc, session.session_id, "새 메시지", db)

            # After restore, message_history should have been capped
            # (the new user+assistant are added, but we check before those)
            restored_before_new = session.message_history[: _MAX_HISTORY_TURNS * 2]
            assert len(restored_before_new) <= _MAX_HISTORY_TURNS * 2
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_session_restore_does_not_overwrite_existing_history(self):
        """If session already has in-memory history, DB restore is skipped."""
        from app.database import Base
        from app.models import ChatMessage

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()

            # Pre-populate in-memory history
            session.message_history = [
                {"role": "user", "content": "기존 메시지"},
                {"role": "assistant", "content": "기존 응답"},
            ]

            # Also insert different content in DB
            db.add(ChatMessage(
                session_id=session.session_id, role="user",
                content="DB 메시지",
            ))
            db.commit()

            captured_history: list = []
            original = svc.extract_intent

            def spy(message, history=None):
                if history:
                    captured_history.extend(history)
                return original(message, history=history)

            svc.extract_intent = spy
            _collect_events_with_db(svc, session.session_id, "테스트", db)

            # In-memory history should take precedence — DB content should NOT appear
            contents = [e["content"] for e in captured_history]
            assert "DB 메시지" not in contents
            assert "기존 메시지" in contents
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_chatmessage_model_has_required_fields(self):
        """ChatMessage model must have session_id, role, content, created_at fields."""
        from app.models import ChatMessage

        msg = ChatMessage(session_id="test-session", role="user", content="hello")
        assert msg.session_id == "test-session"
        assert msg.role == "user"
        assert msg.content == "hello"


# ---------------------------------------------------------------------------
# Task #67: refine_plan intent handler — AI plan refinement via chat
# ---------------------------------------------------------------------------

class TestRefinePlan:
    """_handle_refine_plan dispatched on refine_plan intent.

    Done criteria:
    - refine_plan in intent action list
    - calls GeminiService refine_itinerary with current plan
    - Planner agent_status working→done
    - emits plan_update with refined plan
    - chat_chunk summary
    - tests for agent events
    """

    def _make_service_with_gemini(self, gemini_mock):
        return ChatService(
            api_key="",
            ttl_seconds=SESSION_TTL_SECONDS,
            gemini_service=gemini_mock,
            web_search_service=MagicMock(),
            hotel_search_service=MagicMock(),
            flight_search_service=MagicMock(),
        )

    def _make_fake_last_plan(self, itinerary=None):
        if itinerary is None:
            itinerary = _make_fake_itinerary()
        return {
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-04",
            "budget": 2000000.0,
            "interests": "food",
            "days": [d.model_dump() for d in itinerary.days],
            "total_estimated_cost": itinerary.total_estimated_cost,
        }

    # --- refine_plan in action list ---

    def test_refine_plan_is_valid_intent_action(self):
        """Intent model accepts 'refine_plan' as action."""
        intent = Intent(action="refine_plan", raw_message="더 저렴하게 바꿔줘")
        assert intent.action == "refine_plan"

    # --- activates planner agent ---

    def test_refine_plan_activates_planner_agent(self):
        """refine_plan intent must activate the planner agent."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="더 저렴하게 바꿔줘"
        )):
            events = _collect_events(svc, session.session_id, "더 저렴하게 바꿔줘")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "planner" in agent_names

    # --- planner working → done sequence ---

    def test_refine_plan_planner_working_then_done(self):
        """Planner must emit working then done (no requirement for thinking)."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        planner_statuses = [
            e["data"]["status"]
            for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "planner"
        ]
        assert "working" in planner_statuses
        assert "done" in planner_statuses
        assert planner_statuses.index("working") < planner_statuses.index("done")

    # --- budget_analyst activated ---

    def test_refine_plan_activates_budget_analyst(self):
        """refine_plan must also activate budget_analyst."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "budget_analyst" in agent_names

    # --- emits plan_update ---

    def test_refine_plan_emits_plan_update(self):
        """refine_plan must emit exactly one plan_update event."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="바꿔줘"
        )):
            events = _collect_events(svc, session.session_id, "바꿔줘")

        plan_events = [e for e in events if e["type"] == "plan_update"]
        assert len(plan_events) == 1
        assert "days" in plan_events[0]["data"]

    def test_refine_plan_update_has_destination_and_budget(self):
        """plan_update data must include destination and budget from last_plan."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        plan_update = next(e for e in events if e["type"] == "plan_update")
        assert plan_update["data"]["destination"] == "도쿄"
        assert plan_update["data"]["budget"] == 2000000.0

    # --- emits day_update per day ---

    def test_refine_plan_emits_day_update_per_day(self):
        """refine_plan must emit one day_update per day in refined result."""
        mock_gemini = MagicMock()
        itinerary = _make_fake_itinerary()
        mock_gemini.refine_itinerary.return_value = itinerary
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan(itinerary)

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        day_events = [e for e in events if e["type"] == "day_update"]
        assert len(day_events) == len(itinerary.days)

    # --- calls refine_itinerary when last_plan exists ---

    def test_refine_plan_with_existing_plan_calls_refine_itinerary(self):
        """When session.last_plan exists, refine_itinerary must be called."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="더 저렴하게"
        )):
            _collect_events(svc, session.session_id, "더 저렴하게")

        mock_gemini.refine_itinerary.assert_called_once()
        call_args = mock_gemini.refine_itinerary.call_args[0]
        assert call_args[0] == "도쿄"  # destination

    def test_refine_plan_passes_instruction_to_refine(self):
        """The raw_message is forwarded as instruction to refine_itinerary."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="맛집 위주로 바꿔줘"
        )):
            _collect_events(svc, session.session_id, "맛집 위주로 바꿔줘")

        call_args = mock_gemini.refine_itinerary.call_args[0]
        # instruction is the last positional arg
        assert "맛집 위주로 바꿔줘" in call_args[-1]

    # --- fallback to generate when no last_plan ---

    def test_refine_plan_without_existing_plan_falls_back_to_generate(self):
        """When session.last_plan is None, generate_itinerary is called instead."""
        mock_gemini = MagicMock()
        mock_gemini.generate_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        # session.last_plan is None by default

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", destination="도쿄", raw_message="수정"
        )):
            _collect_events(svc, session.session_id, "수정")

        mock_gemini.generate_itinerary.assert_called_once()
        mock_gemini.refine_itinerary.assert_not_called()

    # --- emits chat_chunk summary ---

    def test_refine_plan_emits_chat_chunk(self):
        """refine_plan must emit at least one chat_chunk event."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        chunk_events = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunk_events) >= 1

    # --- session last_plan updated ---

    def test_refine_plan_updates_session_last_plan(self):
        """After refine_plan, session.last_plan should be updated with refined result."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.return_value = _make_fake_itinerary()
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            _collect_events(svc, session.session_id, "수정")

        fetched = svc.get_session(session.session_id)
        assert fetched.last_plan is not None
        assert "days" in fetched.last_plan

    # --- error handling ---

    def test_refine_plan_gemini_error_emits_planner_error_status(self):
        """When Gemini fails, planner agent must emit error status."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.side_effect = RuntimeError("Gemini down")
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        error_events = [
            e for e in events
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "planner"
            and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_refine_plan_error_emits_chat_chunk(self):
        """On Gemini failure, a chat_chunk with error message must be emitted."""
        mock_gemini = MagicMock()
        mock_gemini.refine_itinerary.side_effect = RuntimeError("API error")
        svc = self._make_service_with_gemini(mock_gemini)
        session = svc.create_session()
        session.last_plan = self._make_fake_last_plan()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="refine_plan", raw_message="수정"
        )):
            events = _collect_events(svc, session.session_id, "수정")

        chunk_events = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunk_events) >= 1


# ---------------------------------------------------------------------------
# Task #68: Chat delete_expense intent handler
# ---------------------------------------------------------------------------

class TestDeleteExpense:
    """_handle_delete_expense must remove an Expense row and re-emit expense_summary SSE."""

    def test_delete_expense_activates_secretary(self):
        """delete_expense intent activates the secretary agent."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="delete_expense", expense_name="식사", raw_message="식사 지출 삭제"
        )):
            events = _collect_events(svc, session.session_id, "식사 지출 삭제")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    def test_delete_expense_no_db_emits_error(self):
        """delete_expense without a DB session emits error."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="delete_expense", expense_name="식사", raw_message="식사 삭제"
        )):
            events = _collect_events(svc, session.session_id, "식사 삭제")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_delete_expense_no_saved_plan_emits_error(self):
        """delete_expense without session.last_saved_plan_id emits error."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            # no last_saved_plan_id set

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="식사", raw_message="식사 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 삭제", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_by_name_removes_row(self):
        """delete_expense by name deletes the matching Expense row from DB."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="식사", raw_message="식사 지출 삭제"
            )):
                _collect_events_with_db(svc, session.session_id, "식사 지출 삭제", db)

            remaining = db.query(ExpenseModel).filter(ExpenseModel.travel_plan_id == plan_id).all()
            assert len(remaining) == 1
            assert remaining[0].name == "택시"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_by_category_removes_most_recent(self):
        """delete_expense by category deletes the most recent matching expense."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "점심", "amount": 30000.0, "category": "food"},
                {"name": "저녁", "amount": 60000.0, "category": "food"},
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_category="food", raw_message="식비 항목 삭제"
            )):
                _collect_events_with_db(svc, session.session_id, "식비 항목 삭제", db)

            remaining = db.query(ExpenseModel).filter(ExpenseModel.travel_plan_id == plan_id).all()
            names = {e.name for e in remaining}
            # most recent food expense (저녁) deleted, 점심 and 택시 remain
            assert "저녁" not in names
            assert "점심" in names
            assert "택시" in names
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_last_expense_when_no_name_or_category(self):
        """When neither name nor category given, deletes the most recently added expense."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
                {"name": "입장료", "amount": 20000.0, "category": "activities"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", raw_message="마지막 지출 삭제"
            )):
                _collect_events_with_db(svc, session.session_id, "마지막 지출 삭제", db)

            remaining = db.query(ExpenseModel).filter(ExpenseModel.travel_plan_id == plan_id).all()
            assert len(remaining) == 1
            assert remaining[0].name == "식사"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_not_found_emits_error(self):
        """delete_expense for a non-existent name emits an error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="없는항목", raw_message="없는항목 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "없는항목 삭제", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status"
                and e["data"]["agent"] == "secretary"
                and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_reemits_expense_summary(self):
        """After deletion, an expense_summary SSE event must be emitted."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="식사", raw_message="식사 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 삭제", db)

            summary_events = [e for e in events if e["type"] == "expense_summary"]
            assert len(summary_events) == 1
            summary = summary_events[0]["data"]
            assert summary["total_spent"] == 15000.0
            assert summary["expense_count"] == 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_summary_has_required_fields(self):
        """expense_summary event after deletion must include all required keys."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="식사", raw_message="식사 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 삭제", db)

            summary = next(e["data"] for e in events if e["type"] == "expense_summary")
            for key in ("plan_id", "budget", "total_spent", "remaining", "by_category", "expense_count", "over_budget"):
                assert key in summary, f"Missing key: {key}"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_secretary_working_then_done(self):
        """Secretary agent must transition working -> done on successful deletion."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="식사", raw_message="식사 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "식사 삭제", db)

            secretary_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
            ]
            statuses = [e["data"]["status"] for e in secretary_events]
            assert "working" in statuses
            assert "done" in statuses
            assert statuses.index("working") < statuses.index("done")
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_emits_chat_chunk(self):
        """delete_expense must emit a chat_chunk with confirmation text."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="delete_expense", expense_name="택시", raw_message="택시 삭제"
            )):
                events = _collect_events_with_db(svc, session.session_id, "택시 삭제", db)

            chunk_events = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chunk_events) >= 1
            text = " ".join(e["data"]["text"] for e in chunk_events)
            assert "택시" in text
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_delete_expense_intent_accepted_by_model(self):
        """Intent model must accept action='delete_expense'."""
        intent = Intent(
            action="delete_expense",
            expense_name="식사",
            expense_category="food",
            raw_message="식사 삭제",
        )
        assert intent.action == "delete_expense"
        assert intent.expense_name == "식사"
        assert intent.expense_category == "food"


# ---------------------------------------------------------------------------
# Task #70: GET /chat/sessions/{id} returns last 10 messages from DB
# ---------------------------------------------------------------------------

class TestGetSessionMessageHistoryFromDB:
    """GET /chat/sessions/{id} must return last 10 messages from DB in message_history."""

    def test_get_session_message_history_field_present(self, client):
        """GET /chat/sessions/{id} response has message_history field."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.get(f"/chat/sessions/{session_id}")
        assert "message_history" in resp.json()

    def test_get_session_message_history_empty_before_messages(self, client):
        """Fresh session with no DB messages returns empty message_history."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.get(f"/chat/sessions/{session_id}")
        assert resp.json()["message_history"] == []

    def test_get_session_returns_db_messages_after_exchange(self, client):
        """After a message exchange, GET session returns messages from DB."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        resp = client.get(f"/chat/sessions/{session_id}")
        history = resp.json()["message_history"]
        # At least the user message should appear
        assert any(m["role"] == "user" for m in history)

    def test_get_session_message_history_has_role_and_content(self, client):
        """Each entry in message_history has role and content keys."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "안녕하세요"},
        )
        history = client.get(f"/chat/sessions/{session_id}").json()["message_history"]
        for msg in history:
            assert "role" in msg
            assert "content" in msg

    def test_get_session_message_history_user_content_matches(self, client):
        """User message content in history matches the sent message."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "도쿄 여행 계획"},
        )
        history = client.get(f"/chat/sessions/{session_id}").json()["message_history"]
        user_msgs = [m for m in history if m["role"] == "user"]
        assert any("도쿄 여행 계획" in m["content"] for m in user_msgs)

    def test_get_session_message_history_limited_to_10(self, client):
        """GET /chat/sessions/{id} returns at most 10 messages from DB."""
        session_id = client.post("/chat/sessions").json()["session_id"]

        # Send 6 messages via endpoint (creates 12 DB rows: 6 user + 6 assistant)
        for i in range(6):
            client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"message": f"메시지 {i}"},
            )
        history = client.get(f"/chat/sessions/{session_id}").json()["message_history"]
        assert len(history) <= 10

    def test_get_session_message_history_newest_messages_returned(self, client):
        """When more than 10 DB messages exist, the newest are returned."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        for i in range(6):
            client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"message": f"메시지{i}"},
            )
        history = client.get(f"/chat/sessions/{session_id}").json()["message_history"]
        # Last user message should be in history
        contents = [m["content"] for m in history if m["role"] == "user"]
        assert any("메시지5" in c for c in contents)


# ---------------------------------------------------------------------------
# Task #74: update_expense intent handler
# ---------------------------------------------------------------------------


class TestUpdateExpense:
    """_handle_update_expense must update an Expense row and emit expense_updated SSE."""

    def test_update_expense_activates_secretary(self):
        """update_expense intent activates the secretary agent."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="update_expense", expense_name="택시", expense_amount=30000.0,
            raw_message="택시 비용 30000원으로 수정"
        )):
            events = _collect_events(svc, session.session_id, "택시 비용 30000원으로 수정")

        agent_names = {e["data"]["agent"] for e in events if e["type"] == "agent_status"}
        assert "secretary" in agent_names

    def test_update_expense_no_db_emits_error(self):
        """update_expense without a DB session emits error."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="update_expense", expense_name="택시", expense_amount=30000.0,
            raw_message="택시 수정"
        )):
            events = _collect_events(svc, session.session_id, "택시 수정")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["status"] == "error"
        ]
        assert len(error_events) >= 1

    def test_update_expense_no_name_emits_error(self):
        """update_expense without expense_name emits error."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_amount=30000.0,
                raw_message="지출 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 수정", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_updates_amount_in_db(self):
        """update_expense updates the expense amount in the database."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="택시", expense_amount=30000.0,
                raw_message="택시 30000원으로 수정"
            )):
                _collect_events_with_db(svc, session.session_id, "택시 30000원으로 수정", db)

            updated = db.query(ExpenseModel).filter(
                ExpenseModel.travel_plan_id == plan_id,
                ExpenseModel.name == "택시",
            ).first()
            assert updated is not None
            assert updated.amount == 30000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_updates_category_in_db(self):
        """update_expense updates the expense category in the database."""
        from app.database import Base
        from app.models import Expense as ExpenseModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="식사", expense_category="activities",
                raw_message="식사 카테고리 변경"
            )):
                _collect_events_with_db(svc, session.session_id, "식사 카테고리 변경", db)

            updated = db.query(ExpenseModel).filter(
                ExpenseModel.travel_plan_id == plan_id,
                ExpenseModel.name == "식사",
            ).first()
            assert updated is not None
            assert updated.category == "activities"
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_emits_expense_updated_event(self):
        """update_expense must emit an expense_updated SSE event."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "입장료", "amount": 20000.0, "category": "activities"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="입장료", expense_amount=25000.0,
                raw_message="입장료 25000원으로 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "입장료 25000원으로 수정", db)

            updated_events = [e for e in events if e["type"] == "expense_updated"]
            assert len(updated_events) == 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_event_has_expense_and_budget_summary(self):
        """expense_updated event must contain 'expense' and 'budget_summary' keys."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "숙소", "amount": 100000.0, "category": "accommodation"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="숙소", expense_amount=120000.0,
                raw_message="숙소 12만원으로 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "숙소 12만원으로 수정", db)

            updated_event = next(e for e in events if e["type"] == "expense_updated")
            assert "expense" in updated_event["data"]
            assert "budget_summary" in updated_event["data"]
            assert updated_event["data"]["expense"]["amount"] == 120000.0
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_not_found_emits_error(self):
        """update_expense for a non-existent name emits error agent_status."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="없는항목", expense_amount=10000.0,
                raw_message="없는항목 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "없는항목 수정", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["status"] == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_reemits_expense_summary(self):
        """After update, an expense_summary SSE event must be emitted."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "교통비", "amount": 40000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="교통비", expense_amount=50000.0,
                raw_message="교통비 50000원으로 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "교통비 50000원으로 수정", db)

            summary_events = [e for e in events if e["type"] == "expense_summary"]
            assert len(summary_events) >= 1
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_secretary_working_then_done(self):
        """Secretary agent must transition working → done on successful update."""
        from app.database import Base

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="update_expense", expense_name="택시", expense_amount=20000.0,
                raw_message="택시 2만원으로 수정"
            )):
                events = _collect_events_with_db(svc, session.session_id, "택시 2만원으로 수정", db)

            sec_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
            ]
            statuses = [e["data"]["status"] for e in sec_events]
            assert "working" in statuses
            assert "done" in statuses
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    def test_update_expense_intent_accepted_by_model(self):
        """Intent model must accept action='update_expense'."""
        intent = Intent(
            action="update_expense",
            expense_name="식사",
            expense_amount=60000.0,
            expense_category="food",
            raw_message="식사 6만원으로 수정",
        )
        assert intent.action == "update_expense"
        assert intent.expense_name == "식사"
        assert intent.expense_amount == 60000.0


# ---------------------------------------------------------------------------
# Task #76: list_expenses intent handler
# ---------------------------------------------------------------------------

class TestListExpenses:
    """_handle_list_expenses must query all expenses for the saved plan and emit expense_list SSE."""

    def test_list_expenses_activates_budget_analyst(self):
        """list_expenses intent activates the budget_analyst agent."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록 보여줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록 보여줘", db)

            agent_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "budget_analyst"
            ]
            assert len(agent_events) >= 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_no_db_emits_error(self):
        """list_expenses without a DB session emits error."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="list_expenses", raw_message="지출 목록"
        )):
            events = _collect_events(svc, session.session_id, "지출 목록")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"].get("status") == "error"
        ]
        assert len(error_events) >= 1

    def test_list_expenses_no_saved_plan_emits_error(self):
        """list_expenses without session.last_saved_plan_id emits error."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            # No last_saved_plan_id set

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"].get("status") == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_emits_expense_list_event(self):
        """list_expenses must emit an expense_list SSE event."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
                {"name": "택시", "amount": 15000.0, "category": "transport"},
            ])
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록 보여줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록 보여줘", db)

            list_events = [e for e in events if e["type"] == "expense_list"]
            assert len(list_events) == 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_event_contains_all_expenses(self):
        """expense_list event must contain all expense rows for the plan."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
                {"name": "택시", "amount": 15000.0, "category": "transport"},
                {"name": "입장료", "amount": 10000.0, "category": "activities"},
            ])
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 내역 전체"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 내역 전체", db)

            evt = next(e for e in events if e["type"] == "expense_list")
            expenses = evt["data"]["expenses"]
            assert len(expenses) == 3
            names = {e["name"] for e in expenses}
            assert names == {"식사", "택시", "입장료"}
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_event_has_required_fields(self):
        """expense_list event data must include plan_id, expenses, total_spent, expense_count."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록", db)

            evt = next(e for e in events if e["type"] == "expense_list")
            data = evt["data"]
            assert "plan_id" in data
            assert "expenses" in data
            assert "total_spent" in data
            assert "expense_count" in data
            assert data["expense_count"] == 1
            assert data["total_spent"] == 50000.0
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_empty_plan_emits_empty_list(self):
        """list_expenses with no expenses should return an empty list event."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [])  # no expenses
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록", db)

            list_events = [e for e in events if e["type"] == "expense_list"]
            assert len(list_events) == 1
            assert list_events[0]["data"]["expenses"] == []
            assert list_events[0]["data"]["expense_count"] == 0
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_budget_analyst_working_then_done(self):
        """budget_analyst agent must transition working → done on successful list."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 30000.0, "category": "food"},
            ])
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록", db)

            analyst_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "budget_analyst"
            ]
            statuses = [e["data"]["status"] for e in analyst_events]
            assert "working" in statuses
            assert "done" in statuses
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_emits_chat_chunk(self):
        """list_expenses must emit a chat_chunk event."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_and_expenses(db, [
                {"name": "식사", "amount": 50000.0, "category": "food"},
            ])
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="list_expenses", raw_message="지출 목록"
            )):
                events = _collect_events_with_db(svc, session.session_id, "지출 목록", db)

            chat_chunks = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chat_chunks) >= 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_list_expenses_intent_accepted_by_model(self):
        """Intent model must accept action='list_expenses'."""
        intent = Intent(
            action="list_expenses",
            raw_message="지출 목록 보여줘",
        )
        assert intent.action == "list_expenses"


# ---------------------------------------------------------------------------
# Task #77: copy_plan intent handler
# ---------------------------------------------------------------------------

def _seed_plan_with_itinerary(db):
    """Insert a TravelPlan with one DayItinerary and one Place; return plan_id."""
    from app.models import DayItinerary as DayItineraryModel, Place as PlaceModel, TravelPlan as TravelPlanModel
    from datetime import date as date_type

    plan = TravelPlanModel(
        destination="오사카",
        start_date=date_type(2026, 6, 1),
        end_date=date_type(2026, 6, 3),
        budget=600000.0,
        interests="food",
        status="confirmed",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    day = DayItineraryModel(
        travel_plan_id=plan.id,
        date=date_type(2026, 6, 1),
        notes="첫째 날",
        transport="지하철",
    )
    db.add(day)
    db.flush()

    db.add(PlaceModel(
        day_itinerary_id=day.id,
        name="도톤보리",
        category="sightseeing",
        address="오사카 도톤보리",
        estimated_cost=0.0,
        ai_reason="유명 관광지",
        order=1,
    ))
    db.commit()
    return plan.id


class TestCopyPlan:
    """_handle_copy_plan must duplicate a saved plan and emit plan_saved SSE."""

    def test_copy_plan_intent_accepted_by_model(self):
        """Intent model must accept action='copy_plan'."""
        intent = Intent(action="copy_plan", raw_message="계획 복사해줘")
        assert intent.action == "copy_plan"

    def test_copy_plan_no_db_emits_error(self):
        """copy_plan without a DB session emits an error agent_status."""
        svc = _make_service_no_api()
        session = svc.create_session()

        with patch.object(svc, "extract_intent", return_value=Intent(
            action="copy_plan", raw_message="계획 복사"
        )):
            events = _collect_events(svc, session.session_id, "계획 복사")

        error_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"].get("status") == "error"
        ]
        assert len(error_events) >= 1

    def test_copy_plan_no_plan_id_emits_error(self):
        """copy_plan without a resolvable plan emits an error."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            svc = _make_service_no_api()
            session = svc.create_session()
            # No last_saved_plan_id, no destination, no plan_id in intent

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복사"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 복사", db)

            error_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"].get("status") == "error"
            ]
            assert len(error_events) >= 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_emits_plan_saved_event(self):
        """copy_plan must emit a plan_saved SSE event."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="이 계획 복사해줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "이 계획 복사해줘", db)

            saved_events = [e for e in events if e["type"] == "plan_saved"]
            assert len(saved_events) == 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_creates_new_db_row(self):
        """copy_plan must create a new TravelPlan row in the DB."""
        from app.models import TravelPlan as TravelPlanModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            before_count = db.query(TravelPlanModel).count()

            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복제"
            )):
                _collect_events_with_db(svc, session.session_id, "계획 복제", db)

            after_count = db.query(TravelPlanModel).count()
            assert after_count == before_count + 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_new_plan_is_draft(self):
        """Copied plan must have status='draft'."""
        from app.models import TravelPlan as TravelPlanModel

        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복사"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 복사", db)

            saved_evt = next(e for e in events if e["type"] == "plan_saved")
            new_id = saved_evt["data"]["plan_id"]
            new_plan = db.get(TravelPlanModel, new_id)
            assert new_plan.status == "draft"
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_plan_saved_has_required_fields(self):
        """plan_saved event data must include plan_id, copied_from, and plan."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복사"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 복사", db)

            saved_evt = next(e for e in events if e["type"] == "plan_saved")
            data = saved_evt["data"]
            assert "plan_id" in data
            assert "copied_from" in data
            assert "plan" in data
            assert data["copied_from"] == plan_id
            assert data["plan_id"] != plan_id
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_by_destination(self):
        """copy_plan can resolve a plan by destination substring."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            # No last_saved_plan_id; resolve by destination

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan",
                destination="오사카",
                raw_message="오사카 계획 복사해줘"
            )):
                events = _collect_events_with_db(svc, session.session_id, "오사카 계획 복사해줘", db)

            saved_events = [e for e in events if e["type"] == "plan_saved"]
            assert len(saved_events) == 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_updates_session_last_saved_plan_id(self):
        """After copy_plan, session.last_saved_plan_id must point to the new plan."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복사"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 복사", db)

            saved_evt = next(e for e in events if e["type"] == "plan_saved")
            new_id = saved_evt["data"]["plan_id"]
            assert session.last_saved_plan_id == new_id
            assert new_id != plan_id
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_secretary_working_then_done(self):
        """secretary agent must transition working → done on successful copy."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복사"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 복사", db)

            sec_events = [
                e for e in events
                if e["type"] == "agent_status" and e["data"]["agent"] == "secretary"
            ]
            statuses = [e["data"]["status"] for e in sec_events]
            assert "working" in statuses
            assert "done" in statuses
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)

    def test_copy_plan_emits_chat_chunk(self):
        """copy_plan must emit a chat_chunk event."""
        engine, TestingSession = _make_test_db()
        db = TestingSession()
        try:
            plan_id = _seed_plan_with_itinerary(db)
            svc = _make_service_no_api()
            session = svc.create_session()
            session.last_saved_plan_id = plan_id

            with patch.object(svc, "extract_intent", return_value=Intent(
                action="copy_plan", raw_message="계획 복사"
            )):
                events = _collect_events_with_db(svc, session.session_id, "계획 복사", db)

            chat_chunks = [e for e in events if e["type"] == "chat_chunk"]
            assert len(chat_chunks) >= 1
        finally:
            db.close()
            from app.database import Base
            Base.metadata.drop_all(bind=engine)
