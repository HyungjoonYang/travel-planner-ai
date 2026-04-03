"""ChatService: session management + intent extraction + SSE agent-status events."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import GEMINI_API_KEY

SESSION_TTL_SECONDS = 1800  # 30 minutes


class Intent(BaseModel):
    action: str  # create_plan | modify_day | search_places | search_hotels | search_flights | save_plan | general
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: Optional[float] = None
    interests: Optional[str] = None
    day_number: Optional[int] = None
    query: Optional[str] = None
    raw_message: str = ""


class ChatSession(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime
    history: list[dict] = []


class ChatService:
    def __init__(self, api_key: str = "", ttl_seconds: int = SESSION_TTL_SECONDS):
        self._api_key = api_key or GEMINI_API_KEY
        self._ttl = ttl_seconds
        self._sessions: dict[str, ChatSession] = {}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self) -> ChatSession:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        session = ChatSession(
            session_id=session_id,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if datetime.now(timezone.utc) > session.expires_at:
            del self._sessions[session_id]
            return None
        return session

    def expire_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    # ------------------------------------------------------------------
    # Intent extraction
    # ------------------------------------------------------------------

    def extract_intent(self, message: str) -> Intent:
        """Extract structured intent from user message via Gemini API.

        Falls back to action='general' if API key is missing or call fails.
        """
        if not self._api_key:
            return Intent(action="general", raw_message=message)

        try:
            prompt = f"""You are a travel planner AI assistant. Analyze the user message and extract their intent.

User message: "{message}"

Return a JSON object with these fields:
- action: one of "create_plan", "modify_day", "search_places", "search_hotels", "search_flights", "save_plan", "general"
- destination: destination city/country if mentioned, else null
- start_date: start date in YYYY-MM-DD if mentioned, else null
- end_date: end date in YYYY-MM-DD if mentioned, else null
- budget: budget as a number if mentioned, else null
- interests: comma-separated interests if mentioned, else null
- day_number: specific day number if modifying a day, else null
- query: search query string if searching, else null
- raw_message: the exact original message"""

            client = genai.Client(api_key=self._api_key)
            response = client.models.generate_content(
                model="gemini-3.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Intent,
                ),
            )
            intent = Intent.model_validate_json(response.text)
            intent.raw_message = message
            return intent
        except Exception:
            return Intent(action="general", raw_message=message)

    # ------------------------------------------------------------------
    # Message processing (async generator → SSE events)
    # ------------------------------------------------------------------

    async def process_message(
        self,
        session_id: str,
        message: str,
    ) -> AsyncGenerator[dict, None]:
        """Process a user message and yield SSE event dicts."""
        session = self.get_session(session_id)
        if session is None:
            yield {"type": "error", "data": {"message": "Session not found or expired"}}
            return

        # Coordinator always goes first
        yield {
            "type": "agent_status",
            "data": {"agent": "coordinator", "status": "thinking", "message": "요청 분석 중..."},
        }

        intent = self.extract_intent(message)

        yield {
            "type": "agent_status",
            "data": {
                "agent": "coordinator",
                "status": "done",
                "message": f"{intent.action} 파악",
            },
        }

        session.history.append({
            "role": "user",
            "content": message,
            "intent": intent.model_dump(),
        })

        # Dispatch to intent handlers
        if intent.action == "create_plan":
            async for event in self._handle_create_plan(intent):
                yield event
        elif intent.action == "search_hotels":
            async for event in self._handle_search_hotels(intent):
                yield event
        elif intent.action == "search_flights":
            async for event in self._handle_search_flights(intent):
                yield event
        elif intent.action == "search_places":
            async for event in self._handle_search_places(intent):
                yield event
        elif intent.action == "save_plan":
            async for event in self._handle_save_plan(intent):
                yield event
        else:
            yield {
                "type": "chat_chunk",
                "data": {"text": "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."},
            }

        yield {"type": "chat_done", "data": {}}

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_create_plan(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "working", "message": f"{dest} 장소 검색 중..."},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "working", "message": "예산 배분 계산 중..."},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": "일정 구성 준비 중..."},
        }
        await asyncio.sleep(0)
        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "done", "message": "장소 검색 완료"},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "done", "message": "예산 배분 완료"},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "done", "message": "일정 완성!"},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": f"{dest} 여행 계획을 생성했습니다."},
        }

    async def _handle_search_hotels(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        yield {
            "type": "agent_status",
            "data": {"agent": "hotel_finder", "status": "working", "message": f"{dest} 숙소 검색 중..."},
        }
        await asyncio.sleep(0)
        yield {
            "type": "agent_status",
            "data": {"agent": "hotel_finder", "status": "done", "message": "숙소 검색 완료"},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": f"{dest} 숙소를 검색했습니다."},
        }

    async def _handle_search_flights(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        yield {
            "type": "agent_status",
            "data": {"agent": "flight_finder", "status": "working", "message": f"{dest} 항공편 검색 중..."},
        }
        await asyncio.sleep(0)
        yield {
            "type": "agent_status",
            "data": {"agent": "flight_finder", "status": "done", "message": "항공편 검색 완료"},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": f"{dest} 항공편을 검색했습니다."},
        }

    async def _handle_search_places(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "working", "message": f"{dest} 장소 검색 중..."},
        }
        await asyncio.sleep(0)
        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "done", "message": "장소 검색 완료"},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": f"{dest} 장소를 검색했습니다."},
        }

    async def _handle_save_plan(self, intent: Intent) -> AsyncGenerator[dict, None]:
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "여행 계획 저장 중..."},
        }
        await asyncio.sleep(0)
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "done", "message": "저장 완료!"},
        }
        yield {
            "type": "plan_saved",
            "data": {"message": "여행 계획이 저장되었습니다."},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": "여행 계획이 저장되었습니다."},
        }


# Module-level singleton used by the chat router
chat_service = ChatService()
