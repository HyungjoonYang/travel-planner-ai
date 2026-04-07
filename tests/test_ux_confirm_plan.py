"""Tests for UX Phase 2: Confirm Plan Before Auto-Planning.

Plan: /markdowns/feat-ux-improvements.md

Covers:
- _general_with_gemini emits confirm_plan instead of auto-creating plan
- _general_fallback emits confirm_plan instead of auto-creating plan
- confirm_plan intent handler creates plan from pending_plan
- Session stores pending_plan data
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
from app.chat import ChatService, Intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_events(service: ChatService, session_id: str, message: str) -> list[dict]:
    async def _run():
        events = []
        async for event in service.process_message(session_id, message):
            events.append(event)
        return events
    return asyncio.run(_run())


def _make_itinerary_result() -> AIItineraryResult:
    return AIItineraryResult(
        days=[
            AIDayItinerary(
                date="2026-05-01",
                places=[
                    AIPlace(name="Senso-ji", category="sightseeing", estimated_cost=15),
                ],
            ),
        ],
        total_estimated_cost=15.0,
    )


def _make_gemini_general_response_with_all_fields() -> dict:
    """Gemini response where all travel fields are extracted."""
    return {
        "response": "도쿄 5월 여행, 200만원 예산이시군요!",
        "destination": "도쿄",
        "start_date": "2026-05-01",
        "end_date": "2026-05-03",
        "budget": 2000000,
        "interests": "음식, 문화",
    }


# ---------------------------------------------------------------------------
# Phase 2A: _general_with_gemini emits confirm_plan, NOT auto-create
# ---------------------------------------------------------------------------

class TestGeneralGeminiConfirmPlan:
    """When all travel fields are gathered via general conversation,
    the system must emit a confirm_plan event instead of immediately
    calling _handle_create_plan."""

    def test_emits_confirm_plan_when_all_fields_gathered(self):
        """With all fields (dest, dates, budget), should emit confirm_plan, not plan_update."""
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "general", "raw_message": "도쿄 5월 3일간 200만원"})

        conv_resp = MagicMock()
        conv_resp.text = json.dumps(_make_gemini_general_response_with_all_fields())

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [intent_resp, conv_resp]

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 5월 3일간 200만원")

        event_types = [e["type"] for e in events]
        assert "confirm_plan" in event_types, "Should emit confirm_plan event"
        assert "plan_update" not in event_types, (
            "Should NOT auto-create plan (no plan_update without confirmation)"
        )

    def test_confirm_plan_event_contains_trip_details(self):
        """The confirm_plan event must contain the extracted trip details."""
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "general", "raw_message": "도쿄"})

        conv_resp = MagicMock()
        conv_resp.text = json.dumps(_make_gemini_general_response_with_all_fields())

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [intent_resp, conv_resp]

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄")

        confirm_events = [e for e in events if e["type"] == "confirm_plan"]
        assert len(confirm_events) == 1
        data = confirm_events[0]["data"]
        assert data["destination"] == "도쿄"
        assert data["start_date"] == "2026-05-01"
        assert data["end_date"] == "2026-05-03"
        assert data["budget"] == 2000000

    def test_no_confirm_plan_when_fields_missing(self):
        """If not all fields gathered, should NOT emit confirm_plan."""
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "general", "raw_message": "도쿄 가고 싶어"})

        conv_resp = MagicMock()
        conv_resp.text = json.dumps({
            "response": "도쿄 여행이요! 언제쯤 가실 예정인가요?",
            "destination": "도쿄",
            "start_date": None,
            "end_date": None,
            "budget": None,
            "interests": None,
        })

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [intent_resp, conv_resp]

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 가고 싶어")

        event_types = [e["type"] for e in events]
        assert "confirm_plan" not in event_types
        assert "plan_update" not in event_types


# ---------------------------------------------------------------------------
# Phase 2B: _general_fallback emits confirm_plan
# ---------------------------------------------------------------------------

class TestFallbackConfirmPlan:
    """The no-API-key fallback path must also emit confirm_plan
    instead of auto-creating when all fields are known."""

    def test_fallback_emits_confirm_plan_when_all_known(self):
        """Fallback with dest+dates+budget in history → confirm_plan, not plan_update."""
        svc = ChatService(api_key="")
        session = svc.create_session()
        # Seed history with all needed info
        session.message_history = [
            {"role": "user", "content": "도쿄 가고 싶어"},
            {"role": "assistant", "content": "언제쯤 가실 예정인가요?"},
            {"role": "user", "content": "5월 1일부터 3일까지"},
            {"role": "assistant", "content": "예산은 어느 정도로 생각하세요?"},
            {"role": "user", "content": "200만원"},
        ]
        # The intent with budget info
        intent = Intent(
            action="general",
            destination="도쿄",
            start_date="2026-05-01",
            end_date="2026-05-03",
            budget=2000000,
            raw_message="200만원",
        )
        with patch.object(svc, "extract_intent", return_value=intent):
            events = _collect_events(svc, session.session_id, "200만원")

        event_types = [e["type"] for e in events]
        assert "confirm_plan" in event_types, "Fallback should emit confirm_plan"
        assert "plan_update" not in event_types, "Fallback should NOT auto-create plan"


# ---------------------------------------------------------------------------
# Phase 2C: Session stores pending_plan
# ---------------------------------------------------------------------------

class TestPendingPlanSession:
    """When confirm_plan is emitted, the session must store the pending plan
    so that confirm_plan intent can retrieve it."""

    def test_session_has_pending_plan_after_confirm(self):
        """After confirm_plan event, session.pending_plan must contain trip details."""
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "general", "raw_message": "여행"})

        conv_resp = MagicMock()
        conv_resp.text = json.dumps(_make_gemini_general_response_with_all_fields())

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [intent_resp, conv_resp]

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            _collect_events(svc, session.session_id, "여행")

        assert session.pending_plan is not None, "Session must store pending_plan"
        assert session.pending_plan["destination"] == "도쿄"
        assert session.pending_plan["budget"] == 2000000


# ---------------------------------------------------------------------------
# Phase 2D: confirm_plan intent handler
# ---------------------------------------------------------------------------

class TestConfirmPlanHandler:
    """When user confirms (action='confirm_plan'), the system should
    create the plan using the stored pending_plan data."""

    def test_confirm_plan_creates_plan(self):
        """confirm_plan action should trigger _handle_create_plan with pending data."""
        mock_client = MagicMock()
        # Intent extraction returns confirm_plan
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "confirm_plan", "raw_message": "네 세워줘"})
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            # Pre-set pending_plan as if confirm_plan was previously emitted
            session.pending_plan = {
                "destination": "도쿄",
                "start_date": "2026-05-01",
                "end_date": "2026-05-03",
                "budget": 2000000,
                "interests": "음식, 문화",
            }
            events = _collect_events(svc, session.session_id, "네 세워줘")

        event_types = [e["type"] for e in events]
        assert "plan_update" in event_types, "confirm_plan should create the plan"

    def test_confirm_plan_clears_pending_plan(self):
        """After creating plan, pending_plan should be cleared."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "confirm_plan", "raw_message": "좋아 세워줘"})
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            session.pending_plan = {
                "destination": "도쿄",
                "start_date": "2026-05-01",
                "end_date": "2026-05-03",
                "budget": 2000000,
                "interests": "",
            }
            _collect_events(svc, session.session_id, "좋아 세워줘")

        assert session.pending_plan is None, "pending_plan should be cleared after confirmation"

    def test_confirm_plan_without_pending_returns_error(self):
        """If no pending_plan exists, confirm_plan should respond with guidance."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "confirm_plan", "raw_message": "세워줘"})
        mock_client.models.generate_content.return_value = intent_resp

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            # No pending_plan set
            events = _collect_events(svc, session.session_id, "세워줘")

        chunks = [e for e in events if e["type"] == "chat_chunk"]
        assert len(chunks) >= 1, "Should have at least one chat response"
        # Should guide user to provide trip details, not crash
        text = " ".join(c["data"]["text"] for c in chunks)
        assert len(text) > 0
