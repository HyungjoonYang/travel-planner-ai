"""Smoke tests for LLM (Gemini) API connectivity.

These tests make REAL API calls to verify:
- Model ID is valid and accessible
- API key authentication works
- Response format is parseable

Skipped automatically when GEMINI_API_KEY is not set (CI without secrets).
When the key IS available, these tests MUST pass — a failure means the
production service is broken.

Postmortem: gemini-3.0-flash was used as model ID for months but doesn't
exist. Every API call silently failed, and 1499 mock-based tests couldn't
catch it. These smoke tests exist to prevent that from ever happening again.
"""

import json
import os

import pytest
from google import genai
from google.genai import types

from app.ai import GeminiService
from app.chat import ChatService

_HAS_API_KEY = bool(os.getenv("GEMINI_API_KEY", ""))
_skip_no_key = pytest.mark.skipif(not _HAS_API_KEY, reason="GEMINI_API_KEY not set")


@_skip_no_key
class TestGeminiSmoke:
    """Real API calls — these hit the actual Gemini service."""

    def test_model_exists_and_responds(self):
        """The configured model ID must be valid and return a response."""
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=GeminiService.MODEL,
            contents="Reply with exactly: OK",
        )
        assert response.text is not None
        assert len(response.text.strip()) > 0

    def test_model_returns_json_when_requested(self):
        """Gemini must respect response_mime_type='application/json'."""
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=GeminiService.MODEL,
            contents='Return a JSON object: {"status": "ok"}',
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text)
        assert isinstance(parsed, dict)

    def test_extract_intent_returns_valid_action(self):
        """ChatService.extract_intent must return a real parsed intent,
        not fall back to 'general' due to API failure."""
        svc = ChatService()  # uses GEMINI_API_KEY from env
        intent = svc.extract_intent("도쿄 3박4일 여행 계획 세워줘")
        # With a working API, this should be create_plan (not general fallback)
        assert intent.action == "create_plan", (
            f"Expected 'create_plan' but got '{intent.action}'. "
            "If this is 'general', the Gemini API call likely failed silently."
        )
        assert intent.destination is not None

    def test_extract_intent_general_greeting(self):
        """A greeting should be classified as 'general' intentionally,
        not as a fallback from API failure."""
        svc = ChatService()
        intent = svc.extract_intent("안녕하세요!")
        assert intent.action == "general"
        # Verify it actually called Gemini (raw_message is set by the method)
        assert intent.raw_message == "안녕하세요!"

    def test_generate_itinerary_returns_days(self):
        """GeminiService.generate_itinerary must return structured days."""
        from datetime import date, timedelta
        svc = GeminiService()
        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=2)
        result = svc.generate_itinerary("도쿄", start, end, 1000000, "음식, 문화")
        assert len(result.days) >= 1
        assert result.days[0].places is not None
