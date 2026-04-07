"""Tests for UX Phase 1: Fast Response + Multi-Step Bubble + Thinking Config.

Plan: /markdowns/feat-ux-improvements.md

Covers:
- Fast response (chat_chunk) emitted BEFORE intent extraction
- Progress events emitted during handler work (same bubble)
- Gemini thinking_config set to appropriate levels per call type
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

from app.ai import AIItineraryResult, AIDayItinerary, AIPlace, GeminiService
from app.chat import ChatService


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


def _make_gemini_mock(intent_dict: dict, conversation_text: str = "안녕하세요!") -> MagicMock:
    """Create a mock Gemini client that returns intent on first call, conversation on second."""
    intent_resp = MagicMock()
    intent_resp.text = json.dumps(intent_dict)

    conv_resp = MagicMock()
    conv_resp.text = json.dumps({"response": conversation_text}) if isinstance(conversation_text, str) else conversation_text

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [intent_resp, conv_resp]
    return mock_client


def _make_itinerary_result() -> AIItineraryResult:
    return AIItineraryResult(
        days=[
            AIDayItinerary(
                date="2026-05-01",
                places=[
                    AIPlace(name="Senso-ji", category="sightseeing", estimated_cost=15),
                    AIPlace(name="Tsukiji Market", category="food", estimated_cost=25),
                ],
            ),
        ],
        total_estimated_cost=40.0,
    )


# ---------------------------------------------------------------------------
# Phase 1A: Fast response BEFORE intent extraction
# ---------------------------------------------------------------------------

class TestFastResponse:
    """A fast acknowledgment chat_chunk must appear BEFORE the coordinator
    finishes intent extraction, so the user sees an immediate reply."""

    def test_fast_response_chunk_before_coordinator_done(self):
        """A chat_chunk event must appear before the coordinator 'done' event."""
        mock_client = _make_gemini_mock(
            {"action": "general", "raw_message": "안녕"},
            "안녕하세요! 여행 계획을 도와드릴게요.",
        )
        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "안녕")

        # Find the indices
        first_chunk_idx = next(
            (i for i, e in enumerate(events) if e["type"] == "chat_chunk"),
            None,
        )
        coordinator_done_idx = next(
            (i for i, e in enumerate(events)
             if e["type"] == "agent_status"
             and e["data"]["agent"] == "coordinator"
             and e["data"]["status"] == "done"),
            None,
        )
        assert first_chunk_idx is not None, "No chat_chunk event found"
        assert coordinator_done_idx is not None, "No coordinator done event found"
        assert first_chunk_idx < coordinator_done_idx, (
            f"Fast response (idx={first_chunk_idx}) must come before "
            f"coordinator done (idx={coordinator_done_idx})"
        )

    def test_fast_response_is_non_empty(self):
        """The fast response chunk must contain non-empty text."""
        mock_client = _make_gemini_mock(
            {"action": "general", "raw_message": "안녕"},
        )
        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "안녕")

        coordinator_done_idx = next(
            i for i, e in enumerate(events)
            if e["type"] == "agent_status"
            and e["data"]["agent"] == "coordinator"
            and e["data"]["status"] == "done"
        )
        # Get all chat_chunks before coordinator done
        early_chunks = [
            e for i, e in enumerate(events)
            if e["type"] == "chat_chunk" and i < coordinator_done_idx
        ]
        assert len(early_chunks) >= 1
        assert early_chunks[0]["data"]["text"].strip() != ""

    def test_fast_response_for_create_plan_intent(self):
        """Even for create_plan, a fast ack should come before heavy work."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "budget": 2000,
            "raw_message": "도쿄 여행 계획 세워줘",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 여행 계획 세워줘")

        # There should be a chat_chunk before any agent goes to "working"
        first_chunk_idx = next(
            (i for i, e in enumerate(events) if e["type"] == "chat_chunk"),
            None,
        )
        first_working_idx = next(
            (i for i, e in enumerate(events)
             if e["type"] == "agent_status" and e["data"]["status"] == "working"),
            None,
        )
        assert first_chunk_idx is not None, "No chat_chunk found"
        assert first_working_idx is not None, "No working agent found"
        assert first_chunk_idx < first_working_idx, (
            "Fast response must come before agents start working"
        )


# ---------------------------------------------------------------------------
# Phase 1B: Progress events in bubble
# ---------------------------------------------------------------------------

class TestProgressEvents:
    """Progress events let the frontend show step-by-step updates
    inside the same chat bubble."""

    def test_create_plan_emits_progress_events(self):
        """create_plan handler should emit progress events during work."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "budget": 2000,
            "raw_message": "도쿄 여행",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 여행")

        progress_events = [e for e in events if e["type"] == "progress"]
        assert len(progress_events) >= 1, "Should emit at least one progress event"

    def test_progress_event_has_step_and_message(self):
        """Each progress event must have step and message fields."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "파리",
            "raw_message": "파리 여행",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "파리 여행")

        progress_events = [e for e in events if e["type"] == "progress"]
        for evt in progress_events:
            assert "step" in evt["data"], "progress event must have 'step'"
            assert "message" in evt["data"], "progress event must have 'message'"
            assert evt["data"]["step"] != ""
            assert evt["data"]["message"] != ""

    def test_progress_events_before_final_chat_chunk(self):
        """Progress events should appear before the final result chat_chunk."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "도쿄",
            "raw_message": "도쿄",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄")

        progress_indices = [i for i, e in enumerate(events) if e["type"] == "progress"]
        # The last chat_chunk is the final result message
        chunk_indices = [i for i, e in enumerate(events) if e["type"] == "chat_chunk"]
        assert len(progress_indices) >= 1
        assert len(chunk_indices) >= 1
        # At least one progress event should come before the last chat_chunk
        assert min(progress_indices) < max(chunk_indices)


# ---------------------------------------------------------------------------
# Phase 1C: Gemini thinking_config
# ---------------------------------------------------------------------------

class TestThinkingConfig:
    """Gemini calls must use appropriate thinking_level to reduce latency."""

    def test_extract_intent_uses_minimal_thinking(self):
        """extract_intent should use thinking_level='minimal' for fast classification."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"action": "general", "raw_message": "hi"})
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            svc.extract_intent("hi")

        call_kwargs = mock_client.models.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config is not None, "generate_content must be called with config"
        assert hasattr(config, "thinking_config"), "config must have thinking_config"
        level = config.thinking_config.thinking_level
        level_str = level.value if hasattr(level, "value") else str(level)
        assert level_str.upper() == "MINIMAL"

    def test_general_conversation_uses_low_thinking(self):
        """_general_with_gemini should use thinking_level='low' for fast conversation."""
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({"action": "general", "raw_message": "안녕"})

        conv_resp = MagicMock()
        conv_resp.text = json.dumps({"response": "안녕하세요!"})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [intent_resp, conv_resp]

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key")
            session = svc.create_session()
            _collect_events(svc, session.session_id, "안녕")

        # Second call is the conversation call
        calls = mock_client.models.generate_content.call_args_list
        assert len(calls) >= 2, "Should have at least 2 Gemini calls (intent + conversation)"
        conv_call = calls[1]
        # _general_with_gemini uses asyncio.to_thread, so check positional or keyword args
        config = conv_call.kwargs.get("config") or (conv_call[1].get("config") if len(conv_call) > 1 else None)
        assert config is not None, "conversation call must have config"
        assert hasattr(config, "thinking_config"), "config must have thinking_config"
        level = config.thinking_config.thinking_level
        level_str = level.value if hasattr(level, "value") else str(level)
        assert level_str.upper() == "LOW"

    def test_generate_itinerary_uses_medium_thinking(self):
        """GeminiService.generate_itinerary should use thinking_level='medium'."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = _make_itinerary_result().model_dump_json()
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.ai.genai.Client", return_value=mock_client):
            from datetime import date
            svc = GeminiService(api_key="fake-key")
            svc.generate_itinerary("Tokyo", date(2026, 5, 1), date(2026, 5, 3), 2000)

        config = mock_client.models.generate_content.call_args.kwargs.get("config")
        assert config is not None
        assert hasattr(config, "thinking_config")
        level = config.thinking_config.thinking_level
        level_str = level.value if hasattr(level, "value") else str(level)
        assert level_str.upper() == "MEDIUM"

    def test_refine_itinerary_uses_medium_thinking(self):
        """GeminiService.refine_itinerary should use thinking_level='medium'."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = _make_itinerary_result().model_dump_json()
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.ai.genai.Client", return_value=mock_client):
            from datetime import date
            svc = GeminiService(api_key="fake-key")
            svc.refine_itinerary(
                "Tokyo", date(2026, 5, 1), date(2026, 5, 3), 2000, "",
                [{"date": "2026-05-01", "places": []}],
                "add more food spots",
            )

        config = mock_client.models.generate_content.call_args.kwargs.get("config")
        assert config is not None
        assert hasattr(config, "thinking_config")
        level = config.thinking_config.thinking_level
        level_str = level.value if hasattr(level, "value") else str(level)
        assert level_str.upper() == "MEDIUM"

    def test_suggest_improvements_uses_medium_thinking(self):
        """GeminiService.suggest_improvements should use thinking_level='medium'."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Here are some suggestions..."
        mock_client.models.generate_content.return_value = mock_resp

        with patch("app.ai.genai.Client", return_value=mock_client):
            svc = GeminiService(api_key="fake-key")
            svc.suggest_improvements({"destination": "Tokyo"}, [])

        config = mock_client.models.generate_content.call_args.kwargs.get("config")
        assert config is not None
        assert hasattr(config, "thinking_config")
        level = config.thinking_config.thinking_level
        level_str = level.value if hasattr(level, "value") else str(level)
        assert level_str.upper() == "MEDIUM"
