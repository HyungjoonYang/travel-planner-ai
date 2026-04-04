"""Tests for Task #39: ChatService 기본 구조.

Done criteria:
- ChatService가 메시지를 받아 intent JSON을 반환
- 세션 생성/조회/만료 동작
- 테스트 통과
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.chat import ChatService, Intent, SESSION_TTL_SECONDS


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
