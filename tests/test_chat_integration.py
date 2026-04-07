"""Integration tests for the chat pipeline.

These tests verify the FULL request → intent extraction → handler → SSE response
flow WITHOUT mocking core logic like extract_intent.

Only external API calls (Gemini, web search) are mocked at the HTTP/client level,
while internal processing (intent parsing, response generation, DB writes) runs
for real.

These tests are designed to catch bugs like:
- Hardcoded fallback responses repeating regardless of user input
- Intent extraction failures silently falling through to else branch
- SSE stream not containing contextual responses
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

from app.chat import ChatService, chat_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(raw: str) -> list[dict]:
    """Parse SSE text into a list of event dicts."""
    events = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _get_chat_chunks_text(events: list[dict]) -> str:
    """Extract concatenated text from chat_chunk events."""
    return " ".join(
        e["data"].get("text", "")
        for e in events
        if e["type"] == "chat_chunk"
    )


def _collect_events_async(svc: ChatService, session_id: str, message: str, db=None) -> list[dict]:
    """Collect all events from process_message synchronously."""
    async def _run():
        events = []
        async for event in svc.process_message(session_id, message, db=db):
            events.append(event)
        return events
    return asyncio.run(_run())


def _make_gemini_mock_response(intent_dict: dict, conversation_response: str = "") -> MagicMock:
    """Create a mock Gemini client that handles both extract_intent and
    _general_with_gemini calls.

    The first call returns the intent JSON (for extract_intent).
    If the intent is 'general', the second call returns a conversation
    JSON with the response text (for _general_with_gemini).
    """
    intent_response = MagicMock()
    intent_response.text = json.dumps(intent_dict)

    if intent_dict.get("action") == "general" and not conversation_response:
        conversation_response = f"네, 알겠습니다. {intent_dict.get('raw_message', '')}"

    # For streaming phase: text reply as stream chunks
    stream_chunk = MagicMock()
    stream_chunk.text = conversation_response

    # For extraction phase: JSON fields
    extract_dict = {
        "destination": intent_dict.get("destination"),
        "start_date": intent_dict.get("start_date"),
        "end_date": intent_dict.get("end_date"),
        "budget": intent_dict.get("budget"),
        "interests": intent_dict.get("interests"),
    }
    extract_response = MagicMock()
    extract_response.text = json.dumps(extract_dict)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [intent_response, extract_response]
    mock_client.models.generate_content_stream.return_value = [stream_chunk]
    return mock_client


# ===========================================================================
# Test 1: Full-flow integration — Gemini intent extraction runs for real
#          (only the HTTP call is mocked, parsing/dispatch is real)
# ===========================================================================

class TestChatFullFlowIntegration:
    """Integration tests that mock only the Gemini HTTP response,
    not extract_intent itself. The full pipeline runs for real."""

    def test_create_plan_intent_extracted_and_dispatched(self):
        """User says '도쿄 3박4일 여행 계획 세워줘' →
        Gemini returns create_plan intent → plan_update event emitted."""
        svc = ChatService(api_key="test-key-for-integration")
        session = svc.create_session()
        session.pending_plan = {"destination": "도쿄", "start_date": "2026-05-01", "end_date": "2026-05-04", "budget": 1500000, "interests": "음식, 문화"}

        # Mock only the Gemini HTTP client, not extract_intent
        gemini_intent = {
            "action": "create_plan",
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-04",
            "budget": 1500000,
            "interests": "음식, 문화",
            "raw_message": "도쿄 3박4일 여행 계획 세워줘",
        }
        mock_client = _make_gemini_mock_response(gemini_intent)

        with patch("app.chat.genai.Client", return_value=mock_client):
            events = _collect_events_async(svc, session.session_id, "도쿄 3박4일 여행 계획 세워줘")

        # Verify intent was extracted (coordinator done event shows the action)
        coordinator_done = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "coordinator"
            and e["data"]["status"] == "done"
        ]
        assert len(coordinator_done) == 1
        assert "create_plan" in coordinator_done[0]["data"]["message"]

        # Verify plan_update or planner agent activated (not fallback)
        agent_names = {
            e["data"]["agent"]
            for e in events
            if e["type"] == "agent_status"
        }
        assert "planner" in agent_names, "Planner agent should activate for create_plan"

    def test_general_intent_with_api_key_gives_contextual_response(self):
        """When Gemini classifies as 'general', the response should still be
        contextual — not a hardcoded fallback. This test catches the current bug."""
        svc = ChatService(api_key="test-key-for-integration")
        session = svc.create_session()

        gemini_intent = {
            "action": "general",
            "raw_message": "안녕하세요! 여행 추천해주세요",
        }
        mock_client = _make_gemini_mock_response(gemini_intent)

        with patch("app.chat.genai.Client", return_value=mock_client):
            events = _collect_events_async(svc, session.session_id, "안녕하세요! 여행 추천해주세요")

        response_text = _get_chat_chunks_text(events)
        assert response_text, "Should have a response"

        # The response should NOT be the hardcoded fallback every time
        # This is the EXACT bug: no matter what you say, you get this same line
        HARDCODED_FALLBACK = "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."

        # For a greeting + recommendation request, a good AI would engage
        # At minimum, the response should acknowledge what the user said
        # Currently this test WILL FAIL because general → hardcoded fallback
        assert response_text != HARDCODED_FALLBACK, (
            f"Response should be contextual, not hardcoded fallback. Got: {response_text}"
        )


# ===========================================================================
# Test 2: Fallback response repetition detection
# ===========================================================================

class TestFallbackRepetitionDetection:
    """Tests that detect the exact production bug: sending different messages
    but always getting the same hardcoded response."""

    def test_different_messages_produce_different_responses(self):
        """Sending 3 different messages should NOT produce the exact same response
        for all of them. This catches the 'broken record' bug."""
        svc = ChatService(api_key="test-key-for-integration")
        session = svc.create_session()

        messages = [
            "5월에 일본 가고 싶어",
            "예산은 200만원이야",
            "뭔소리야 방금 말했잖아",
        ]

        # For each message, Gemini returns general (simulating the current failure)
        responses = []
        for msg in messages:
            gemini_intent = {"action": "general", "raw_message": msg}
            mock_client = _make_gemini_mock_response(gemini_intent)

            with patch("app.chat.genai.Client", return_value=mock_client):
                events = _collect_events_async(svc, session.session_id, msg)

            response_text = _get_chat_chunks_text(events)
            responses.append(response_text)

        # All 3 responses should NOT be identical
        unique_responses = set(responses)
        assert len(unique_responses) > 1, (
            f"All {len(messages)} different messages produced the same response: "
            f"'{responses[0]}'. The chat is a broken record."
        )

    def test_no_api_key_still_gives_meaningful_response(self):
        """Even without an API key, the chat should not just repeat
        a hardcoded line. It should at least acknowledge the user's input."""
        svc = ChatService(api_key="")  # No API key
        session = svc.create_session()

        events = _collect_events_async(
            svc, session.session_id,
            "5월 1일부터 5일까지 일본 여행 계획 세워줘"
        )

        response_text = _get_chat_chunks_text(events)
        HARDCODED_FALLBACK = "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."

        # The user already PROVIDED destination and dates!
        # Responding with "목적지, 날짜, 예산을 알려주세요" is absurd.
        assert response_text != HARDCODED_FALLBACK, (
            "User already provided destination+dates but got asked for them again. "
            f"Got: '{response_text}'"
        )

    def test_conversation_context_is_preserved(self):
        """Multi-turn: if user says destination first, then dates,
        the system should accumulate context, not reset each time."""
        svc = ChatService(api_key="test-key-for-integration")
        session = svc.create_session()

        # Turn 1: user gives destination
        gemini_intent_1 = {
            "action": "general",
            "destination": "일본",
            "raw_message": "일본 가고 싶어",
        }
        mock_client_1 = _make_gemini_mock_response(gemini_intent_1)
        with patch("app.chat.genai.Client", return_value=mock_client_1):
            _collect_events_async(svc, session.session_id, "일본 가고 싶어")

        # Turn 2: user adds dates
        gemini_intent_2 = {
            "action": "create_plan",
            "destination": "일본",
            "start_date": "2026-05-01",
            "end_date": "2026-05-05",
            "raw_message": "5월 1일부터 5일까지",
        }
        mock_client_2 = _make_gemini_mock_response(gemini_intent_2)
        with patch("app.chat.genai.Client", return_value=mock_client_2):
            events_2 = _collect_events_async(svc, session.session_id, "5월 1일부터 5일까지")

        # Second turn should trigger create_plan, not repeat fallback
        coordinator_done = [
            e for e in events_2
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "coordinator"
            and e["data"]["status"] == "done"
        ]
        assert len(coordinator_done) == 1
        assert "create_plan" in coordinator_done[0]["data"]["message"], (
            "After providing destination + dates across turns, "
            "system should trigger create_plan, not stay in general fallback"
        )

        # Verify message_history was passed to Gemini (the mock was called with context)
        assert len(session.message_history) >= 3, (
            f"Message history should contain at least 3 entries (user1, assistant1, user2), "
            f"got {len(session.message_history)}"
        )


# ===========================================================================
# Test 3: HTTP-level integration via TestClient
# ===========================================================================

class TestChatEndpointIntegration:
    """Test the full HTTP endpoint: POST /chat/sessions/{id}/messages
    These use the real FastAPI app with TestClient."""

    def test_send_message_returns_contextual_sse(self, client):
        """POST a message via HTTP → SSE stream should contain
        agent_status and chat_chunk events with real content."""
        # Create session
        resp = client.post("/chat/sessions")
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        # Prepare mock: Gemini returns create_plan
        gemini_intent = {
            "action": "create_plan",
            "destination": "파리",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "budget": 3000000,
            "interests": "미술, 음식",
            "raw_message": "파리 여행 계획 세워줘",
        }
        mock_client = _make_gemini_mock_response(gemini_intent)

        with (
            patch.object(chat_service, "_api_key", "test-key"),
            patch("app.chat.genai.Client", return_value=mock_client),
        ):
            resp = client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"message": "파리 여행 계획 세워줘"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse_events(resp.text)
        assert len(events) >= 3, f"Expected multiple SSE events, got {len(events)}"

        # Must have coordinator thinking → done
        coordinator_events = [
            e for e in events
            if e["type"] == "agent_status" and e["data"]["agent"] == "coordinator"
        ]
        assert any(e["data"]["status"] == "done" for e in coordinator_events)

        # Must NOT be the hardcoded fallback
        response_text = _get_chat_chunks_text(events)
        HARDCODED_FALLBACK = "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."
        assert response_text != HARDCODED_FALLBACK, (
            "HTTP endpoint returned hardcoded fallback instead of processing the intent"
        )

    def test_sse_stream_ends_with_chat_done(self, client):
        """Every SSE stream must end with a chat_done event."""
        resp = client.post("/chat/sessions")
        session_id = resp.json()["session_id"]

        gemini_intent = {"action": "general", "raw_message": "안녕"}
        mock_client = _make_gemini_mock_response(gemini_intent)

        with patch("app.chat.genai.Client", return_value=mock_client):
            resp = client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"message": "안녕"},
            )

        events = _parse_sse_events(resp.text)
        assert events, "SSE stream should not be empty"
        assert events[-1]["type"] == "chat_done", (
            f"Last event should be chat_done, got: {events[-1]['type']}"
        )

    def test_multiple_turns_via_http_no_repeated_fallback(self, client):
        """Send 3 different messages via HTTP. Responses should not all be identical.

        The module-level chat_service singleton has no API key, so it uses
        _general_fallback. We patch _api_key so it takes the Gemini path,
        and mock genai.Client so we control responses.
        """
        resp = client.post("/chat/sessions")
        session_id = resp.json()["session_id"]

        turns = [
            (
                "오사카 추천해줘",
                {"action": "general", "destination": "오사카", "raw_message": "오사카 추천해줘"},
                "오사카 좋은 선택이에요! 언제쯤 여행을 계획하고 계신가요?",
            ),
            (
                "예산은 100만원",
                {"action": "general", "budget": 1000000, "raw_message": "예산은 100만원"},
                "100만원이면 충분해요. 여행 날짜는 정하셨나요?",
            ),
            (
                "3박4일로 계획 세워줘",
                {"action": "create_plan", "destination": "오사카", "start_date": "2026-05-01", "end_date": "2026-05-04", "budget": 1000000, "raw_message": "3박4일로 계획 세워줘"},
                "",
            ),
        ]

        responses = []
        for msg, intent_dict, conv_text in turns:
            mock_client = _make_gemini_mock_response(intent_dict, conv_text)
            with (
                patch.object(chat_service, "_api_key", "test-key"),
                patch("app.chat.genai.Client", return_value=mock_client),
            ):
                resp = client.post(
                    f"/chat/sessions/{session_id}/messages",
                    json={"message": msg},
                )
            events = _parse_sse_events(resp.text)
            response_text = _get_chat_chunks_text(events)
            responses.append(response_text)

        unique = set(responses)
        assert len(unique) > 1, (
            f"3 different messages all got same response: '{responses[0]}'"
        )

        # The third message (create_plan) should definitely not be the fallback
        HARDCODED_FALLBACK = "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."
        assert responses[2] != HARDCODED_FALLBACK, (
            "create_plan intent should trigger plan generation, not fallback"
        )
