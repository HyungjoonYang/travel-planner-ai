"""ChatService: session management + intent extraction + SSE agent-status events."""

import asyncio
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, AsyncGenerator, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.ai import GeminiService
from app.llm_logger import log_llm_call, LLMTimer
from app.calendar_service import CalendarService
from app.config import GEMINI_API_KEY
from app.flight_search import FlightSearchService
from app.hotel_search import HotelSearchService
from app.web_search import WebSearchService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.ai import AIItineraryResult

SESSION_TTL_SECONDS = 1800  # 30 minutes
_MAX_HISTORY_TURNS = 10     # max conversation turns kept in message_history

_DEFAULT_DEPARTURE = "서울(ICN)"  # default origin for flight search


class Intent(BaseModel):
    action: str  # create_plan | confirm_plan | modify_day | refine_plan | search_places | search_hotels | search_flights | save_plan | export_calendar | list_plans | delete_plan | view_plan | add_expense | update_expense | update_plan | get_expense_summary | delete_expense | list_expenses | copy_plan | get_weather | reset_conversation | add_day_note | suggest_improvements | remove_place | add_place | share_plan | reorder_days | clear_day | general
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: Optional[float] = None
    interests: Optional[str] = None
    day_number: Optional[int] = None
    day_number_2: Optional[int] = None  # second day for reorder_days swap
    plan_id: Optional[int] = None
    query: Optional[str] = None
    access_token: Optional[str] = None
    expense_name: Optional[str] = None
    expense_amount: Optional[float] = None
    expense_category: Optional[str] = None
    place_index: Optional[int] = None  # 1-based place index for remove_place
    place_category: Optional[str] = None  # category for add_place (e.g. "sightseeing", "food", "cafe")
    raw_message: str = ""


class ChatSession(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime
    history: list[dict] = []
    message_history: list[dict] = []   # last N turns for Gemini context (role/content pairs)
    agent_states: dict[str, dict] = {}  # last known agent_status per agent
    last_plan: Optional[dict] = None    # last plan_update payload
    last_saved_plan_id: Optional[int] = None  # DB plan_id after save_plan
    pending_plan: Optional[dict] = None  # trip details awaiting user confirmation
    plan_context: Optional[dict] = None  # progressive travel context (partial info)


class ChatService:
    def __init__(
        self,
        api_key: str = "",
        ttl_seconds: int = SESSION_TTL_SECONDS,
        gemini_service: Optional[GeminiService] = None,
        web_search_service: Optional[WebSearchService] = None,
        hotel_search_service: Optional[HotelSearchService] = None,
        flight_search_service: Optional[FlightSearchService] = None,
    ):
        self._api_key = api_key or GEMINI_API_KEY
        self._ttl = ttl_seconds
        self._sessions: dict[str, ChatSession] = {}
        self._gemini = gemini_service or GeminiService(api_key=self._api_key)
        self._web_search = web_search_service or WebSearchService(api_key=self._api_key)
        self._hotel_search = hotel_search_service or HotelSearchService(api_key=self._api_key)
        self._flight_search = flight_search_service or FlightSearchService(api_key=self._api_key)

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

    def reset_conversation(self, session_id: str) -> bool:
        """Clear in-memory message history for a session. Returns True if session exists."""
        session = self.get_session(session_id)
        if session is None:
            return False
        session.history.clear()
        session.message_history.clear()
        return True

    # ------------------------------------------------------------------
    # Fast response — immediate acknowledgment
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_language(text: str) -> str:
        """Detect user language from message text. Returns 'Korean' or 'English'."""
        korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u318e')
        return "Korean" if korean_chars > 0 else "English"

    @staticmethod
    def _build_fast_response(message: str) -> str:
        """Build a quick acknowledgment message based on the user's input."""
        msg_lower = message.lower().strip()
        # Greetings
        greetings = ["안녕", "하이", "hi", "hello", "hey", "ㅎㅇ"]
        if any(msg_lower.startswith(g) for g in greetings):
            return ""  # let streaming handle the greeting reply naturally
        # Confirmation (for confirm_plan)
        confirms = ["네", "응", "좋아", "ㅇㅇ", "확인", "세워줘", "진행", "go", "yes"]
        if any(msg_lower.startswith(c) for c in confirms):
            return "좋아요, 바로 준비해볼게요! ✈️\n"
        # Search-related
        search_keywords = ["검색", "찾아", "호텔", "숙소", "항공", "맛집"]
        if any(kw in msg_lower for kw in search_keywords):
            return "잠깐만요, 찾아볼게요! 🔍\n"
        # Default — empty string so streaming handles it naturally
        return ""

    # ------------------------------------------------------------------
    # Intent extraction
    # ------------------------------------------------------------------

    def extract_intent(self, message: str, history: Optional[list[dict]] = None) -> Intent:
        """Extract structured intent from user message via Gemini API.

        Falls back to action='general' if API key is missing or call fails.
        Accepts optional ``history`` (list of {role, content} dicts) to provide
        conversation context so follow-up messages can resolve references like
        "3일차" or "그 목적지" from prior turns.
        """
        if not self._api_key:
            logger.warning("extract_intent: no API key configured — falling back to general")
            return Intent(action="general", raw_message=message)

        try:
            # Build conversation context section from the last N turns
            context_section = ""
            if history:
                recent = history[-(_MAX_HISTORY_TURNS * 2):]
                lines = [
                    f"{entry.get('role', 'user').capitalize()}: {entry.get('content', '')}"
                    for entry in recent
                ]
                context_section = "\n\nPrevious conversation:\n" + "\n".join(lines) + "\n"

            today_str = date.today().isoformat()
            prompt = f"""You are a travel planner AI assistant. Analyze the user message and extract their intent.
Today's date is {today_str}. When the user mentions dates without a year, assume the current year ({date.today().year}) or next year if the date has already passed.
The user is based in South Korea. Budget values should be in KRW (Korean Won). Departure city defaults to Seoul (ICN).
{context_section}
User message: "{message}"

Return a JSON object with these fields:
- action: one of "create_plan", "confirm_plan", "modify_day", "refine_plan", "search_places", "search_hotels", "search_flights", "save_plan", "list_plans", "delete_plan", "view_plan", "add_expense", "update_expense", "update_plan", "get_expense_summary", "delete_expense", "list_expenses", "copy_plan", "get_weather", "reset_conversation", "add_day_note", "suggest_improvements", "remove_place", "add_place", "share_plan", "reorder_days", "clear_day", "general"
- Use action "confirm_plan" when the user confirms they want to proceed with creating a travel plan (e.g. "네 세워줘", "좋아 계획해줘", "응 진행해", "yes please", "go ahead", "확인")
- IMPORTANT: Use action "general" for casual conversation, questions, opinions, or when the user is discussing/exploring options but NOT explicitly requesting to create or modify a plan. Examples: "후쿠오카 4박 5일은 너무 길지 않을까?" → general (asking opinion), "여행지 추천해줘" → general (asking for suggestions), "벌레 싫은데" → general (sharing preference)
- Use "create_plan" ONLY when the user explicitly asks to CREATE a plan with specific details. Use "refine_plan" ONLY when the user explicitly asks to CHANGE an existing plan (e.g. "일정 수정해줘", "3일차 바꿔줘")
- destination: destination city/country if mentioned or inferred from conversation context, else null
- start_date: start date in YYYY-MM-DD if mentioned or inferred from context, else null
- end_date: end date in YYYY-MM-DD if mentioned or inferred from context, else null
- budget: budget as a number if mentioned or inferred from context, else null
- interests: comma-separated interests if mentioned or inferred from context, else null
- day_number: specific day number if modifying a day, else null
- plan_id: integer plan ID if deleting, viewing, or updating a specific plan (e.g. "3번 계획 삭제" → 3, "3번 계획 수정" → 3), else null
- For update_plan: destination = new destination/title if user wants to rename, budget = new budget value, start_date/end_date = new dates
- query: search query string if searching, else null
- expense_name: expense item name if adding, updating, or deleting an expense (e.g. "식사", "택시", "입장료"), else null; for "마지막 지출 삭제" leave null
- expense_amount: expense amount as a number if adding or updating an expense (e.g. "5만원" → 50000, "$30" → 30), else null
- expense_category: expense category if adding, updating, or deleting an expense (e.g. "food", "transport", "accommodation", "activities"), infer from context, else null; for "식비 삭제" set to "food"
- Use action "delete_expense" when user wants to delete/remove an expense item (e.g. "마지막 지출 삭제", "식비 항목 삭제", "택시 지출 취소")
- Use action "update_expense" when user wants to edit/modify an existing expense item's amount or category (e.g. "택시 비용 30000원으로 수정", "식사 지출 금액 변경", "교통비 카테고리 변경")
- Use action "list_expenses" when user wants to see all expenses / spending items for the current plan (e.g. "지출 목록 보여줘", "지출 내역 전체", "모든 지출 보기", "지출 항목 리스트")
- Use action "copy_plan" when user wants to duplicate/copy a saved travel plan (e.g. "이 계획 복사해줘", "3번 계획 복제", "도쿄 여행 계획 복사", "계획 복사")
- Use action "get_weather" when user wants to know the weather forecast for a destination or trip dates (e.g. "도쿄 날씨 어때?", "여행 기간 날씨 알려줘", "파리 날씨 예보", "weather forecast for Tokyo")
- Use action "add_day_note" when user wants to append a note or memo to a specific day of the itinerary (e.g. "1일차에 메모 추가해줘", "Day 2에 '우산 챙기기' 노트 달아줘", "3일차 노트: 환전 필요", "add note to day 1"); set day_number to the referenced day number and query to the note text
- Use action "suggest_improvements" when user asks for suggestions, improvements, or feedback on their current travel plan (e.g. "개선할 점 있어?", "추천 사항 있어?", "어떻게 더 좋게 할 수 있을까?", "any suggestions?", "how to improve?", "what would you recommend changing?", "더 좋은 방법 있어?", "계획 피드백 줘")
- Use action "remove_place" when user wants to remove/delete a specific place from a day's itinerary (e.g. "1일차 첫 번째 장소 삭제", "Day 2에서 센소지 빼줘", "3일차에서 루브르 박물관 제거", "remove Senso-ji from day 2", "day 1 first place delete"); set day_number to the referenced day, query to the place name if mentioned, and place_index to the 1-based position if an ordinal is mentioned (e.g. "첫 번째" → 1, "두 번째" → 2, "마지막" → -1)
- Use action "add_place" when user wants to add/append a custom place to a specific day (e.g. "1일차에 서울숲 추가해줘", "Day 2에 경복궁 넣어줘", "3일차에 맛집 추가", "add Gyeongbokgung to day 1", "Day 3에 카페 추가"); set day_number to the referenced day, query to the place name, and place_category to the category if mentioned (e.g. "맛집" → "food", "카페" → "cafe", "관광지" → "sightseeing"), else null
- place_index: 1-based index of the place to remove within the day's places list, if an ordinal position is mentioned (e.g. "첫 번째" → 1, "두 번째" → 2); null if removing by name or unspecified
- place_category: category for the place to add (e.g. "sightseeing", "food", "cafe", "museum", "park", "landmark"); null if not specified
- Use action "share_plan" when user wants to share or get a shareable link for the current or a specific travel plan (e.g. "이 계획 공유해줘", "공유 링크 만들어줘", "친구한테 공유하고 싶어", "share this plan", "get a shareable link", "링크 공유", "공유"); set plan_id if a specific plan is referenced
- Use action "reorder_days" when user wants to swap or reorder two days in their itinerary (e.g. "1일차와 3일차 순서 바꿔줘", "Day 2랑 Day 4 교환해줘", "swap day 1 and day 3", "2일차와 4일차 바꿔줘"); set day_number to the first day and day_number_2 to the second day
- day_number_2: second day number for reorder_days swap (e.g. "1일차와 3일차 바꿔줘" → day_number=1, day_number_2=3); null for all other actions
- Use action "clear_day" when user wants to remove ALL places from a specific day (e.g. "3일차 일정 다 지워줘", "Day 2 일정 전부 삭제", "2일차 장소 모두 제거", "clear all places from day 3", "day 1 일정 비워줘"); set day_number to the referenced day
- raw_message: the exact original message"""

            client = genai.Client(api_key=self._api_key)
            with LLMTimer() as timer:
                response = client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=Intent,
                        thinking_config=types.ThinkingConfig(thinking_level="medium"),
                    ),
                )
            intent = Intent.model_validate_json(response.text)
            intent.raw_message = message
            log_llm_call(
                caller="extract_intent",
                model="gemini-3-flash-preview",
                prompt=prompt,
                response_text=response.text,
                latency_ms=timer.elapsed_ms,
                extra={"action": intent.action},
            )
            return intent
        except Exception as exc:
            logger.error("extract_intent: Gemini call failed — %s: %s", type(exc).__name__, exc, exc_info=True)
            return Intent(action="general", raw_message=message)

    # ------------------------------------------------------------------
    # Message processing (async generator → SSE events)
    # ------------------------------------------------------------------

    async def process_message(
        self,
        session_id: str,
        message: str,
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Process a user message and yield SSE event dicts."""
        session = self.get_session(session_id)
        if session is None:
            yield {"type": "error", "data": {"message": "Session not found or expired"}}
            return

        # Restore history from DB on first exchange (when in-memory history is empty)
        if db is not None and not session.message_history:
            from app.models import ChatMessage
            try:
                db_msgs = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(_MAX_HISTORY_TURNS * 2)
                    .all()
                )
                if db_msgs:
                    session.message_history = [
                        {"role": m.role, "content": m.content}
                        for m in reversed(db_msgs)
                    ]
            except Exception:
                pass  # history restore is best-effort

        def _track(event: dict) -> dict:
            """Update session state and return the event unchanged."""
            if event["type"] == "agent_status":
                session.agent_states[event["data"]["agent"]] = event["data"]
            elif event["type"] == "plan_update":
                session.last_plan = event["data"]
            return event

        # Fast response — immediate acknowledgment before heavy intent extraction
        yield {"type": "chat_chunk", "data": {"text": self._build_fast_response(message)}}

        # Coordinator always goes first
        yield _track({
            "type": "agent_status",
            "data": {"agent": "coordinator", "status": "thinking", "message": "요청 분석 중..."},
        })

        intent = self.extract_intent(message, history=list(session.message_history))

        yield _track({
            "type": "agent_status",
            "data": {
                "agent": "coordinator",
                "status": "done",
                "message": f"{intent.action} 파악",
            },
        })

        session.history.append({
            "role": "user",
            "content": message,
            "intent": intent.model_dump(),
        })

        # Add user message to conversation history for future context
        session.message_history.append({"role": "user", "content": message})

        # Collect assistant response chunks to store in message_history
        assistant_chunks: list[str] = []

        def _track_and_collect(event: dict) -> dict:
            """Track state and collect chat_chunk text for message_history."""
            if event["type"] == "chat_chunk":
                assistant_chunks.append(event["data"].get("text", ""))
            return _track(event)

        # Dispatch to intent handlers, tracking state as events flow
        if intent.action == "create_plan":
            async for event in self._handle_create_plan(intent, session=session):
                yield _track_and_collect(event)
        elif intent.action == "confirm_plan":
            async for event in self._handle_confirm_plan(intent, session):
                yield _track_and_collect(event)
        elif intent.action == "search_hotels":
            async for event in self._handle_search_hotels(intent):
                yield _track_and_collect(event)
        elif intent.action == "search_flights":
            async for event in self._handle_search_flights(intent):
                yield _track_and_collect(event)
        elif intent.action == "search_places":
            async for event in self._handle_search_places(intent):
                yield _track_and_collect(event)
        elif intent.action == "modify_day":
            async for event in self._handle_modify_day(intent, session):
                yield _track_and_collect(event)
        elif intent.action == "refine_plan":
            async for event in self._handle_refine_plan(intent, session):
                yield _track_and_collect(event)
        elif intent.action == "save_plan":
            async for event in self._handle_save_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "export_calendar":
            async for event in self._handle_export_calendar(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "list_plans":
            async for event in self._handle_list_plans(db):
                yield _track_and_collect(event)
        elif intent.action == "delete_plan":
            async for event in self._handle_delete_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "view_plan":
            async for event in self._handle_view_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "add_expense":
            async for event in self._handle_add_expense(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "update_expense":
            async for event in self._handle_update_expense(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "update_plan":
            async for event in self._handle_update_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "get_expense_summary":
            async for event in self._handle_get_expense_summary(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "delete_expense":
            async for event in self._handle_delete_expense(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "list_expenses":
            async for event in self._handle_list_expenses(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "copy_plan":
            async for event in self._handle_copy_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "get_weather":
            async for event in self._handle_get_weather(intent, session):
                yield _track_and_collect(event)
        elif intent.action == "reset_conversation":
            async for event in self._handle_reset_conversation(session):
                yield _track_and_collect(event)
        elif intent.action == "add_day_note":
            async for event in self._handle_add_day_note(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "suggest_improvements":
            async for event in self._handle_suggest_improvements(intent, session):
                yield _track_and_collect(event)
        elif intent.action == "remove_place":
            async for event in self._handle_remove_place(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "add_place":
            async for event in self._handle_add_place(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "share_plan":
            async for event in self._handle_share_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "reorder_days":
            async for event in self._handle_reorder_days(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "clear_day":
            async for event in self._handle_clear_day(intent, session, db):
                yield _track_and_collect(event)
        else:  # general
            async for event in self._handle_general(intent, session):
                yield _track_and_collect(event)

        # Append assistant response to message_history and cap at _MAX_HISTORY_TURNS
        assistant_text = " ".join(assistant_chunks) if assistant_chunks else ""
        if assistant_text:
            session.message_history.append({"role": "assistant", "content": assistant_text})
        max_entries = _MAX_HISTORY_TURNS * 2
        if len(session.message_history) > max_entries:
            session.message_history = session.message_history[-max_entries:]

        # Persist messages to DB
        if db is not None:
            from app.models import ChatMessage
            try:
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
                if assistant_text:
                    db.add(ChatMessage(session_id=session_id, role="assistant", content=assistant_text))
                db.commit()
            except Exception:
                db.rollback()

        yield {"type": "chat_done", "data": {}}

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    def _parse_dates(self, intent: Intent, *, require: bool = False) -> tuple[Optional[date], Optional[date]]:
        """Parse start/end dates from intent.

        If *require* is True, returns sensible defaults instead of None
        (used by handlers that must have dates to proceed).
        """
        try:
            start = date.fromisoformat(intent.start_date) if intent.start_date else None
        except ValueError:
            start = None
        try:
            end = date.fromisoformat(intent.end_date) if intent.end_date else None
        except ValueError:
            end = None

        if require:
            if start is None:
                start = date.today() + timedelta(days=30)
            if end is None:
                end = start + timedelta(days=3)
        elif start and not end:
            # If start is given but end is not, default to 3-day trip
            end = start + timedelta(days=3)
        return start, end

    @staticmethod
    def _compute_budget_breakdown(result: "AIItineraryResult") -> dict:
        """Compute per-category cost breakdown from itinerary places.

        Returns a dict with keys: accommodation, transport, food, activities, total.
        """
        _FOOD_KEYWORDS = {"food", "restaurant", "cafe", "dining", "ramen", "sushi",
                          "bar", "drink", "eat", "bakery", "snack", "market"}
        _ACCOMMODATION_KEYWORDS = {"hotel", "accommodation", "hostel", "inn", "lodge", "resort", "stay"}
        _TRANSPORT_KEYWORDS = {"transport", "transit", "train", "bus", "taxi", "flight",
                               "ferry", "subway", "metro", "transfer"}

        breakdown: dict[str, float] = {"accommodation": 0.0, "transport": 0.0, "food": 0.0, "activities": 0.0}
        for day in result.days:
            for place in day.places:
                cat = place.category.lower()
                cost = place.estimated_cost or 0.0
                if any(kw in cat for kw in _FOOD_KEYWORDS):
                    breakdown["food"] += cost
                elif any(kw in cat for kw in _ACCOMMODATION_KEYWORDS):
                    breakdown["accommodation"] += cost
                elif any(kw in cat for kw in _TRANSPORT_KEYWORDS):
                    breakdown["transport"] += cost
                else:
                    breakdown["activities"] += cost
        breakdown["total"] = result.total_estimated_cost
        return {k: round(v, 2) for k, v in breakdown.items()}

    _BROAD_REGIONS = {
        "동남아", "동남아시아", "southeast asia", "유럽", "europe", "미주", "미국",
        "아시아", "asia", "남미", "south america", "아프리카", "africa",
        "중동", "middle east", "오세아니아", "oceania", "북미", "north america",
        "중남미", "latin america", "동유럽", "서유럽", "북유럽", "남유럽",
    }

    async def _handle_create_plan(self, intent: Intent, session: Optional["ChatSession"] = None) -> AsyncGenerator[dict, None]:
        dest = intent.destination
        budget = intent.budget
        interests = intent.interests or ""
        start, end = self._parse_dates(intent)

        # If destination is too broad or essential info is missing,
        # delegate to conversational AI instead of hardcoding responses
        is_broad = dest and dest.lower().strip() in self._BROAD_REGIONS
        missing_fields = not dest or not start or not budget
        if is_broad or missing_fields:
            if session:
                async for event in self._general_with_gemini(intent, session):
                    yield event
            return

        # If not coming from confirm_plan, show confirmation card first
        if session and not session.pending_plan:
            pending = {
                "destination": dest,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "budget": float(budget),
                "interests": interests,
            }
            session.pending_plan = pending
            yield {"type": "chat_chunk", "data": {"text": f"좋아요! {dest} 여행 조건을 정리해봤어요~ 한번 확인해주세요!\n"}}
            yield {"type": "confirm_plan", "data": pending}
            return

        # Clear pending_plan now that we're executing
        if session:
            session.pending_plan = None

        interests_desc = f", 관심사: {interests}" if interests else ""
        yield {
            "type": "agent_reasoning",
            "data": {
                "agent": "planner",
                "reasoning": f"{dest} {(end - start).days + 1}일 여행 계획을 예산 {budget:,.0f}원 기준으로 생성합니다{interests_desc}.",
            },
        }

        yield {"type": "progress", "data": {"step": "search", "message": f"📍 {dest} 장소 검색 중..."}}

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
            "data": {"agent": "planner", "status": "working", "message": "일정 구성 중..."},
        }

        try:
            user_lang = self._detect_language(intent.raw_message or "")
            result = await asyncio.to_thread(
                self._gemini.generate_itinerary,
                dest, start, end, budget, interests, user_lang,
            )

            place_count = sum(len(day.places) for day in result.days)
            yield {"type": "progress", "data": {"step": "places_done", "message": f"✅ {place_count}개 장소 발견"}}
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "place_scout",
                    "status": "done",
                    "message": f"{place_count}개 장소 찾음",
                    "result_count": place_count,
                },
            }
            breakdown = self._compute_budget_breakdown(result)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "budget_analyst",
                    "status": "done",
                    "message": f"총 {result.total_estimated_cost:,.0f}원 예산 배분 완료",
                    "result_count": len(breakdown) - 1,  # exclude "total"
                },
            }
            yield {
                "type": "search_results",
                "data": {"type": "budget", "results": breakdown},
            }

            # Emit full plan (with overview fields) then per-day updates
            plan_data = result.model_dump()
            plan_data["destination"] = dest
            plan_data["start_date"] = start.isoformat()
            plan_data["end_date"] = end.isoformat()
            plan_data["budget"] = budget
            yield {"type": "plan_update", "data": plan_data}
            for day in result.days:
                yield {"type": "day_update", "data": day.model_dump()}

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "planner",
                    "status": "done",
                    "message": f"{len(result.days)}일 일정 완성!",
                },
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"{dest} {len(result.days)}일 여행 계획을 생성했습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "error", "message": "일정 생성 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"일정 생성 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_confirm_plan(
        self, intent: Intent, session: "ChatSession"
    ) -> AsyncGenerator[dict, None]:
        """Handle confirm_plan: create plan from pending_plan stored in session."""
        pending = session.pending_plan
        if not pending:
            yield {
                "type": "chat_chunk",
                "data": {"text": "아직 확정할 여행 조건이 없어요. 어디로 가고 싶으신지부터 얘기해볼까요? 😊"},
            }
            return

        confirmed_intent = Intent(
            action="create_plan",
            destination=pending.get("destination"),
            start_date=pending.get("start_date"),
            end_date=pending.get("end_date"),
            budget=pending.get("budget"),
            interests=pending.get("interests", ""),
            raw_message=intent.raw_message,
        )
        session.pending_plan = None
        async for event in self._handle_create_plan(confirmed_intent):
            yield event

    async def _handle_search_hotels(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        start, end = self._parse_dates(intent, require=True)
        budget_per_night = int(intent.budget / (end - start).days) if intent.budget else 0

        yield {
            "type": "agent_reasoning",
            "data": {
                "agent": "hotel_finder",
                "reasoning": f"{dest}에서 {start} ~ {end} 기간 숙소를 검색합니다. 1박 예산: ${budget_per_night}.",
            },
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "hotel_finder", "status": "working", "message": f"{dest} 숙소 검색 중..."},
        }

        try:
            result = await asyncio.to_thread(
                self._hotel_search.search_hotels,
                dest,
                start.isoformat(),
                end.isoformat(),
                budget_per_night,
            )

            hotel_count = len(result.hotels)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "hotel_finder",
                    "status": "done",
                    "message": f"{hotel_count}개 숙소 찾음",
                    "result_count": hotel_count,
                },
            }
            yield {
                "type": "search_results",
                "data": {"type": "hotels", "results": result.model_dump()},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"{dest} 숙소 {hotel_count}개를 찾았습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "hotel_finder", "status": "error", "message": "숙소 검색 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"숙소 검색 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_search_flights(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        start, end = self._parse_dates(intent, require=True)

        yield {
            "type": "agent_reasoning",
            "data": {
                "agent": "flight_finder",
                "reasoning": f"{_DEFAULT_DEPARTURE} → {dest} 항공편을 {start} 출발 기준으로 검색합니다.",
            },
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "flight_finder", "status": "working", "message": f"{dest} 항공편 검색 중..."},
        }

        try:
            result = await asyncio.to_thread(
                self._flight_search.search_flights,
                _DEFAULT_DEPARTURE,
                dest,
                start.isoformat(),
                end.isoformat(),
            )

            flight_count = len(result.flights)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "flight_finder",
                    "status": "done",
                    "message": f"{flight_count}개 항공편 찾음",
                    "result_count": flight_count,
                },
            }
            yield {
                "type": "search_results",
                "data": {"type": "flights", "results": result.model_dump()},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"{dest} 항공편 {flight_count}개를 찾았습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "flight_finder", "status": "error", "message": "항공편 검색 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"항공편 검색 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_search_places(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        interests = intent.interests or ""

        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "working", "message": f"{dest} 장소 검색 중..."},
        }

        try:
            result = await asyncio.to_thread(
                self._web_search.search_places,
                dest,
                interests,
            )

            place_count = len(result.places)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "place_scout",
                    "status": "done",
                    "message": f"{place_count}개 장소 찾음",
                    "result_count": place_count,
                },
            }
            yield {
                "type": "search_results",
                "data": {"type": "places", "results": result.model_dump()},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"{dest} 장소 {place_count}개를 찾았습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "place_scout", "status": "error", "message": "장소 검색 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"장소 검색 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_modify_day(
        self, intent: Intent, session: "ChatSession"
    ) -> AsyncGenerator[dict, None]:
        day_number = intent.day_number or 1
        instruction = intent.query or intent.raw_message

        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "thinking", "message": f"Day {day_number} 수정 준비 중..."},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": f"Day {day_number} 일정 수정 중..."},
        }

        try:
            last_plan = session.last_plan
            if last_plan:
                dest = last_plan.get("destination", intent.destination or "목적지")
                budget = last_plan.get("budget", intent.budget or 0)
                start_str = last_plan.get("start_date")
                end_str = last_plan.get("end_date")
                try:
                    start = date.fromisoformat(start_str) if start_str else None
                except ValueError:
                    start = None
                try:
                    end = date.fromisoformat(end_str) if end_str else None
                except ValueError:
                    end = None
                if start is None:
                    start = date.today()
                if end is None:
                    end = start + timedelta(days=3)
                current_days = last_plan.get("days", [])

                user_lang = self._detect_language(intent.raw_message or "")
                result = await asyncio.to_thread(
                    self._gemini.refine_itinerary,
                    dest, start, end, budget, intent.interests or "",
                    current_days,
                    f"Day {day_number}: {instruction}",
                    user_lang,
                )
            else:
                dest = intent.destination or "목적지"
                budget = intent.budget or 0
                start, end = self._parse_dates(intent, require=True)
                user_lang = self._detect_language(intent.raw_message or "")

                result = await asyncio.to_thread(
                    self._gemini.generate_itinerary,
                    dest, start, end, budget, intent.interests or "", user_lang,
                )

            day_index = day_number - 1
            if 0 <= day_index < len(result.days):
                updated_day = result.days[day_index]
            elif result.days:
                updated_day = result.days[0]
            else:
                raise ValueError(f"No days returned from Gemini for Day {day_number}")

            yield {"type": "day_update", "data": updated_day.model_dump()}
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "done", "message": f"Day {day_number} 수정 완료!"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"Day {day_number} 일정을 수정했습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "error", "message": f"Day {day_number} 수정 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"일정 수정 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_refine_plan(
        self, intent: Intent, session: "ChatSession"
    ) -> AsyncGenerator[dict, None]:
        """Refine the entire current plan with AI based on user's instruction."""
        instruction = intent.query or intent.raw_message

        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": "전체 일정 개선 중..."},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "working", "message": "예산 재계산 중..."},
        }

        try:
            last_plan = session.last_plan
            if last_plan:
                dest = last_plan.get("destination", intent.destination or "목적지")
                budget = last_plan.get("budget", intent.budget or 0)
                start_str = last_plan.get("start_date")
                end_str = last_plan.get("end_date")
                try:
                    start = date.fromisoformat(start_str) if start_str else None
                except ValueError:
                    start = None
                try:
                    end = date.fromisoformat(end_str) if end_str else None
                except ValueError:
                    end = None
                if start is None:
                    start = date.today()
                if end is None:
                    end = start + timedelta(days=3)
                current_days = last_plan.get("days", [])
                interests = last_plan.get("interests", intent.interests or "")

                user_lang = self._detect_language(intent.raw_message or "")
                result = await asyncio.to_thread(
                    self._gemini.refine_itinerary,
                    dest, start, end, float(budget), interests,
                    current_days,
                    instruction,
                    user_lang,
                )
            else:
                dest = intent.destination or "목적지"
                budget = intent.budget or 0
                interests = intent.interests or ""
                start, end = self._parse_dates(intent, require=True)
                user_lang = self._detect_language(intent.raw_message or "")

                result = await asyncio.to_thread(
                    self._gemini.generate_itinerary,
                    dest, start, end, budget, interests, user_lang,
                )

            place_count = sum(len(day.places) for day in result.days)
            breakdown = self._compute_budget_breakdown(result)

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "budget_analyst",
                    "status": "done",
                    "message": f"총 {result.total_estimated_cost:,.0f}원 예산 재배분 완료",
                    "result_count": len(breakdown) - 1,
                },
            }

            plan_data = result.model_dump()
            plan_data["destination"] = dest
            plan_data["start_date"] = start.isoformat()
            plan_data["end_date"] = end.isoformat()
            plan_data["budget"] = budget
            yield {"type": "plan_update", "data": plan_data}
            for day in result.days:
                yield {"type": "day_update", "data": day.model_dump()}

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "planner",
                    "status": "done",
                    "message": f"{len(result.days)}일 일정 개선 완료!",
                },
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"{dest} 여행 계획을 개선했습니다. {place_count}개 장소, {len(result.days)}일 일정."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "error", "message": "일정 개선 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"일정 개선 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_save_plan(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "여행 계획 저장 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = None
        if db is not None:
            from app.models import TravelPlan as TravelPlanModel

            last_plan = session.last_plan
            if last_plan:
                dest = last_plan.get("destination", intent.destination or "여행 계획")
                start_str = last_plan.get("start_date")
                end_str = last_plan.get("end_date")
                budget = last_plan.get("budget", intent.budget or 0)
                interests = last_plan.get("interests", intent.interests or "")
            else:
                dest = intent.destination or "여행 계획"
                start, end = self._parse_dates(intent, require=True)
                start_str = start.isoformat()
                end_str = end.isoformat()
                budget = intent.budget or 0
                interests = intent.interests or ""

            try:
                start_date = date.fromisoformat(start_str) if start_str else date.today()
            except ValueError:
                start_date = date.today()
            try:
                end_date = date.fromisoformat(end_str) if end_str else start_date
            except ValueError:
                end_date = start_date
            if end_date < start_date:
                end_date = start_date

            plan_record = TravelPlanModel(
                destination=dest,
                start_date=start_date,
                end_date=end_date,
                budget=float(budget),
                interests=interests if isinstance(interests, str) else "",
            )
            db.add(plan_record)
            db.commit()
            db.refresh(plan_record)
            plan_id = plan_record.id
            session.last_saved_plan_id = plan_id

        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "done", "message": "저장 완료!"},
        }
        yield {
            "type": "plan_saved",
            "data": {"message": "여행 계획이 저장되었습니다.", "plan_id": plan_id},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": "여행 계획이 저장되었습니다."},
        }

    async def _handle_export_calendar(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "thinking", "message": "캘린더 내보내기 준비 중..."},
        }
        await asyncio.sleep(0)

        access_token = intent.access_token or ""
        if not access_token:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "Google 인증 토큰이 필요합니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "Google Calendar 내보내기를 위해 Google 계정 연동이 필요합니다."},
            }
            return

        plan_id = session.last_saved_plan_id
        if plan_id is None or db is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "저장된 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "캘린더로 내보내려면 먼저 여행 계획을 저장해주세요."},
            }
            return

        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "Google Calendar에 내보내는 중..."},
        }

        try:
            from app.models import TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                raise ValueError(f"Plan {plan_id} not found in DB")

            cal_service = CalendarService(access_token=access_token)
            result = await asyncio.to_thread(cal_service.export_plan, plan)

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "secretary",
                    "status": "done",
                    "message": f"{result.events_created}개 이벤트 추가됨",
                    "result_count": result.events_created,
                },
            }
            yield {
                "type": "calendar_exported",
                "data": {
                    "plan_id": result.plan_id,
                    "destination": result.destination,
                    "events_created": result.events_created,
                },
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"Google Calendar에 {result.events_created}개 일정이 추가되었습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "캘린더 내보내기 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"캘린더 내보내기 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_list_plans(
        self,
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "저장된 여행 계획 조회 중..."},
        }
        await asyncio.sleep(0)

        if db is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "조회 완료"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "저장된 여행 계획이 없습니다."},
            }
            return

        try:
            from app.models import TravelPlan as TravelPlanModel

            plans = db.query(TravelPlanModel).order_by(TravelPlanModel.created_at.desc()).all()

            plan_count = len(plans)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "secretary",
                    "status": "done",
                    "message": f"{plan_count}개 계획 조회됨",
                    "result_count": plan_count,
                },
            }

            plan_list = [
                {
                    "id": p.id,
                    "destination": p.destination,
                    "start_date": p.start_date.isoformat() if p.start_date else None,
                    "end_date": p.end_date.isoformat() if p.end_date else None,
                    "budget": p.budget,
                    "status": p.status,
                }
                for p in plans
            ]
            yield {
                "type": "plans_list",
                "data": {"plans": plan_list},
            }

            if plans:
                lines = [
                    f"{i + 1}. {p.destination} ({p.start_date} ~ {p.end_date})"
                    for i, p in enumerate(plans)
                ]
                text = f"저장된 여행 계획 {plan_count}개:\n" + "\n".join(lines)
            else:
                text = "저장된 여행 계획이 없습니다."

            yield {
                "type": "chat_chunk",
                "data": {"text": text},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "계획 조회 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"여행 계획 조회 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_delete_plan(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "여행 계획 삭제 중..."},
        }
        await asyncio.sleep(0)

        # Resolve the plan ID: prefer explicit intent.plan_id, then session's last saved plan
        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "삭제할 계획을 찾을 수 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "삭제할 여행 계획을 지정해주세요. (예: '3번 계획 삭제')"},
            }
            return

        try:
            from app.models import TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            destination = plan.destination
            db.delete(plan)
            db.commit()

            # Clear the session's saved plan reference if it matches
            if session.last_saved_plan_id == plan_id:
                session.last_saved_plan_id = None

            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "삭제 완료!"},
            }
            yield {
                "type": "plan_deleted",
                "data": {"plan_id": plan_id, "destination": destination},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"'{destination}' 여행 계획(#{plan_id})이 삭제되었습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "삭제 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"여행 계획 삭제 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_view_plan(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Fetch a saved plan from DB by ID or destination substring and emit plan_update."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "여행 계획 불러오는 중..."},
        }
        await asyncio.sleep(0)

        if db is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "DB가 연결되지 않았습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "여행 계획을 불러오려면 DB 연결이 필요합니다."},
            }
            return

        try:
            from app.models import TravelPlan as TravelPlanModel

            plan: Optional[TravelPlanModel] = None

            # 1. Try exact ID lookup first
            if intent.plan_id is not None:
                plan = db.get(TravelPlanModel, intent.plan_id)

            # 2. Fall back to destination substring search
            if plan is None and intent.destination:
                plan = (
                    db.query(TravelPlanModel)
                    .filter(TravelPlanModel.destination.ilike(f"%{intent.destination}%"))
                    .order_by(TravelPlanModel.created_at.desc())
                    .first()
                )

            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": "계획을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": "해당 여행 계획을 찾을 수 없습니다. 계획 ID나 목적지를 확인해주세요."},
                }
                return

            plan_data = {
                "id": plan.id,
                "destination": plan.destination,
                "start_date": plan.start_date.isoformat() if plan.start_date else None,
                "end_date": plan.end_date.isoformat() if plan.end_date else None,
                "budget": plan.budget,
                "interests": plan.interests,
                "status": plan.status,
                "days": [],
            }

            # Update session state so subsequent save/export/delete can reference this plan
            session.last_plan = plan_data
            session.last_saved_plan_id = plan.id

            yield {"type": "plan_update", "data": plan_data}
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "secretary",
                    "status": "done",
                    "message": f"'{plan.destination}' 계획 불러오기 완료",
                },
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"'{plan.destination}' 여행 계획(#{plan.id})을 불러왔습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "계획 불러오기 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"여행 계획 불러오기 중 오류가 발생했습니다: {exc}"},
            }


    async def _emit_budget_plan_update(
        self,
        session: "ChatSession",
        plan_id: int,
        plan_budget: float,
        total_spent: float,
    ) -> AsyncGenerator[dict, None]:
        """Briefly activate budget_analyst and re-emit plan_update with budget_used + budget_pct."""
        budget_pct = round(total_spent / plan_budget * 100, 1) if plan_budget > 0 else 0.0

        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "thinking", "message": "예산 현황 업데이트 중..."},
        }
        await asyncio.sleep(0)

        # Build plan_update payload — merge into session.last_plan if available
        if session.last_plan is not None:
            plan_data = dict(session.last_plan)
        else:
            plan_data = {"id": plan_id, "budget": plan_budget, "days": []}

        plan_data["budget_used"] = round(total_spent, 2)
        plan_data["budget_pct"] = budget_pct

        yield {"type": "plan_update", "data": plan_data}

        yield {
            "type": "agent_status",
            "data": {
                "agent": "budget_analyst",
                "status": "done",
                "message": f"예산 {budget_pct:.1f}% 사용 ({total_spent:,.0f}원 / {plan_budget:,.0f}원)",
            },
        }


    async def _handle_add_expense(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Add an expense to the current saved plan via the existing Expense API."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "지출 항목 추가 중..."},
        }
        await asyncio.sleep(0)

        # Resolve plan ID
        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "지출을 추가할 여행 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "지출을 추가하려면 먼저 여행 계획을 저장해주세요."},
            }
            return

        # Require at least a name and amount
        expense_name = intent.expense_name or intent.query or intent.raw_message
        expense_amount = intent.expense_amount
        if not expense_amount or expense_amount <= 0:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "금액을 인식할 수 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "지출 금액을 명확히 입력해주세요. (예: '식사 50000원 추가')"},
            }
            return

        try:
            from app.models import Expense as ExpenseModel, TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            expense = ExpenseModel(
                travel_plan_id=plan_id,
                name=expense_name,
                amount=expense_amount,
                category=intent.expense_category or "",
            )
            db.add(expense)
            db.commit()
            db.refresh(expense)

            # Compute updated budget summary
            all_expenses = (
                db.query(ExpenseModel)
                .filter(ExpenseModel.travel_plan_id == plan_id)
                .all()
            )
            total_spent = sum(e.amount for e in all_expenses)
            by_category: dict[str, float] = {}
            for e in all_expenses:
                key = e.category or "other"
                by_category[key] = round(by_category.get(key, 0.0) + e.amount, 2)

            expense_data = {
                "id": expense.id,
                "name": expense.name,
                "amount": expense.amount,
                "category": expense.category,
                "travel_plan_id": plan_id,
            }
            budget_summary = {
                "plan_id": plan_id,
                "budget": plan.budget,
                "total_spent": round(total_spent, 2),
                "remaining": round(plan.budget - total_spent, 2),
                "by_category": by_category,
                "expense_count": len(all_expenses),
                "over_budget": total_spent > plan.budget,
            }

            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "지출 추가 완료!"},
            }
            yield {
                "type": "expense_added",
                "data": {"expense": expense_data, "budget_summary": budget_summary},
            }
            async for evt in self._emit_budget_plan_update(session, plan_id, plan.budget, total_spent):
                yield evt
            over_msg = " (예산 초과!)" if budget_summary["over_budget"] else ""
            yield {
                "type": "chat_chunk",
                "data": {
                    "text": (
                        f"'{expense_name}' {expense_amount:,.0f}원 지출을 추가했습니다."
                        f" 총 지출: {total_spent:,.0f}원{over_msg}"
                    )
                },
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "지출 추가 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"지출 추가 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_update_plan(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Update a saved plan's metadata (budget, destination/title, dates) via chat."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "여행 계획 수정 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "수정할 여행 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "수정할 여행 계획을 찾을 수 없습니다. 먼저 계획을 저장하거나 선택해주세요."},
            }
            return

        try:
            from app.models import TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            updated_fields: list[str] = []

            if intent.budget is not None:
                plan.budget = intent.budget
                updated_fields.append(f"예산: {intent.budget:,.0f}원")

            if intent.destination is not None:
                plan.destination = intent.destination
                updated_fields.append(f"목적지: {intent.destination}")

            if intent.start_date is not None:
                try:
                    plan.start_date = date.fromisoformat(intent.start_date)
                    updated_fields.append(f"시작일: {intent.start_date}")
                except ValueError:
                    pass

            if intent.end_date is not None:
                try:
                    plan.end_date = date.fromisoformat(intent.end_date)
                    updated_fields.append(f"종료일: {intent.end_date}")
                except ValueError:
                    pass

            if not updated_fields:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": "수정할 내용을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": "수정할 내용을 명확히 알려주세요. (예: '예산을 200만원으로 바꿔줘', '날짜를 6월로 변경해줘')"},
                }
                return

            db.commit()
            db.refresh(plan)

            plan_data = {
                "id": plan.id,
                "destination": plan.destination,
                "start_date": plan.start_date.isoformat() if plan.start_date else None,
                "end_date": plan.end_date.isoformat() if plan.end_date else None,
                "budget": plan.budget,
                "interests": plan.interests,
                "status": plan.status,
                "days": [],
            }

            # Update session state
            session.last_plan = plan_data
            session.last_saved_plan_id = plan.id

            yield {"type": "plan_update", "data": plan_data}
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "수정 완료!"},
            }
            changes_text = ", ".join(updated_fields)
            yield {
                "type": "chat_chunk",
                "data": {"text": f"여행 계획(#{plan_id})이 수정되었습니다. 변경 사항: {changes_text}"},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "계획 수정 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"여행 계획 수정 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_get_expense_summary(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Return total/remaining/category expense breakdown for the current plan."""
        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "working", "message": "지출 내역 분석 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "budget_analyst", "status": "error", "message": "분석할 여행 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "지출 내역을 확인하려면 먼저 여행 계획을 저장해주세요."},
            }
            return

        try:
            from app.models import Expense as ExpenseModel, TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "budget_analyst", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            all_expenses = (
                db.query(ExpenseModel)
                .filter(ExpenseModel.travel_plan_id == plan_id)
                .all()
            )
            total_spent = round(sum(e.amount for e in all_expenses), 2)
            by_category: dict[str, float] = {}
            for e in all_expenses:
                key = e.category or "other"
                by_category[key] = round(by_category.get(key, 0.0) + e.amount, 2)

            summary = {
                "plan_id": plan_id,
                "budget": plan.budget,
                "total_spent": total_spent,
                "remaining": round(plan.budget - total_spent, 2),
                "by_category": by_category,
                "expense_count": len(all_expenses),
                "over_budget": total_spent > plan.budget,
            }

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "budget_analyst",
                    "status": "done",
                    "message": f"총 {total_spent:,.0f}원 지출, {summary['remaining']:,.0f}원 남음",
                    "result_count": len(all_expenses),
                },
            }
            yield {"type": "expense_summary", "data": summary}

            over_msg = " (예산 초과!)" if summary["over_budget"] else ""
            if all_expenses:
                cat_lines = [f"  • {cat}: {amt:,.0f}원" for cat, amt in by_category.items()]
                text = (
                    f"총 지출: {total_spent:,.0f}원 / 예산: {plan.budget:,.0f}원{over_msg}\n"
                    f"남은 예산: {summary['remaining']:,.0f}원\n"
                    "카테고리별:\n" + "\n".join(cat_lines)
                )
            else:
                text = f"아직 기록된 지출이 없습니다. 예산: {plan.budget:,.0f}원"

            yield {"type": "chat_chunk", "data": {"text": text}}

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "budget_analyst", "status": "error", "message": "지출 내역 조회 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"지출 내역 조회 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_update_expense(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Update an existing expense's amount and/or category by name."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "지출 항목 수정 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "수정할 여행 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "지출을 수정하려면 먼저 여행 계획을 저장해주세요."},
            }
            return

        if not intent.expense_name:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "수정할 지출 항목명을 알려주세요"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "어떤 지출 항목을 수정할까요? 항목 이름을 알려주세요."},
            }
            return

        try:
            from app.models import Expense as ExpenseModel, TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            expense_to_update: Optional[ExpenseModel] = (
                db.query(ExpenseModel)
                .filter(
                    ExpenseModel.travel_plan_id == plan_id,
                    ExpenseModel.name == intent.expense_name,
                )
                .order_by(ExpenseModel.id.desc())
                .first()
            )

            if expense_to_update is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"'{intent.expense_name}' 항목을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"'{intent.expense_name}' 지출 항목을 찾을 수 없습니다."},
                }
                return

            # Apply updates — only fields provided in the intent
            if intent.expense_amount is not None and intent.expense_amount > 0:
                expense_to_update.amount = intent.expense_amount
            if intent.expense_category is not None:
                expense_to_update.category = intent.expense_category
            db.commit()
            db.refresh(expense_to_update)

            # Compute updated budget summary
            all_expenses = (
                db.query(ExpenseModel)
                .filter(ExpenseModel.travel_plan_id == plan_id)
                .all()
            )
            total_spent = round(sum(e.amount for e in all_expenses), 2)
            by_category: dict[str, float] = {}
            for e in all_expenses:
                key = e.category or "other"
                by_category[key] = round(by_category.get(key, 0.0) + e.amount, 2)

            expense_data = {
                "id": expense_to_update.id,
                "name": expense_to_update.name,
                "amount": expense_to_update.amount,
                "category": expense_to_update.category,
                "travel_plan_id": plan_id,
            }
            budget_summary = {
                "plan_id": plan_id,
                "budget": plan.budget,
                "total_spent": total_spent,
                "remaining": round(plan.budget - total_spent, 2),
                "by_category": by_category,
                "expense_count": len(all_expenses),
                "over_budget": total_spent > plan.budget,
            }

            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "지출 수정 완료!"},
            }
            yield {
                "type": "expense_updated",
                "data": {"expense": expense_data, "budget_summary": budget_summary},
            }
            async for evt in self._emit_budget_plan_update(session, plan_id, plan.budget, total_spent):
                yield evt
            yield {"type": "expense_summary", "data": budget_summary}
            over_msg = " (예산 초과!)" if budget_summary["over_budget"] else ""
            yield {
                "type": "chat_chunk",
                "data": {
                    "text": (
                        f"'{expense_to_update.name}' 지출을 수정했습니다."
                        f" 금액: {expense_to_update.amount:,.0f}원. 총 지출: {total_spent:,.0f}원{over_msg}"
                    )
                },
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "지출 수정 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"지출 수정 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_delete_expense(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Delete an expense from the current saved plan by name, category, or last added."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "지출 항목 삭제 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "삭제할 여행 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "지출을 삭제하려면 먼저 여행 계획을 저장해주세요."},
            }
            return

        try:
            from app.models import Expense as ExpenseModel, TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            # Identify the target expense: by name > by category > latest
            expense_to_delete: Optional[ExpenseModel] = None

            if intent.expense_name:
                expense_to_delete = (
                    db.query(ExpenseModel)
                    .filter(
                        ExpenseModel.travel_plan_id == plan_id,
                        ExpenseModel.name == intent.expense_name,
                    )
                    .order_by(ExpenseModel.id.desc())
                    .first()
                )
            elif intent.expense_category:
                expense_to_delete = (
                    db.query(ExpenseModel)
                    .filter(
                        ExpenseModel.travel_plan_id == plan_id,
                        ExpenseModel.category == intent.expense_category,
                    )
                    .order_by(ExpenseModel.id.desc())
                    .first()
                )
            else:
                # "마지막 지출 삭제" — delete the most recently added expense
                expense_to_delete = (
                    db.query(ExpenseModel)
                    .filter(ExpenseModel.travel_plan_id == plan_id)
                    .order_by(ExpenseModel.id.desc())
                    .first()
                )

            if expense_to_delete is None:
                label = intent.expense_name or intent.expense_category or "마지막 지출"
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": f"'{label}' 항목을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"'{label}' 지출 항목을 찾을 수 없습니다."},
                }
                return

            deleted_name = expense_to_delete.name
            deleted_amount = expense_to_delete.amount
            db.delete(expense_to_delete)
            db.commit()

            # Compute updated budget summary
            remaining_expenses = (
                db.query(ExpenseModel)
                .filter(ExpenseModel.travel_plan_id == plan_id)
                .all()
            )
            total_spent = round(sum(e.amount for e in remaining_expenses), 2)
            by_category: dict[str, float] = {}
            for e in remaining_expenses:
                key = e.category or "other"
                by_category[key] = round(by_category.get(key, 0.0) + e.amount, 2)

            summary = {
                "plan_id": plan_id,
                "budget": plan.budget,
                "total_spent": total_spent,
                "remaining": round(plan.budget - total_spent, 2),
                "by_category": by_category,
                "expense_count": len(remaining_expenses),
                "over_budget": total_spent > plan.budget,
            }

            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "지출 삭제 완료!"},
            }
            yield {
                "type": "expense_deleted",
                "data": {"name": deleted_name, "budget_summary": summary},
            }
            async for evt in self._emit_budget_plan_update(session, plan_id, plan.budget, total_spent):
                yield evt
            yield {"type": "expense_summary", "data": summary}
            yield {
                "type": "chat_chunk",
                "data": {
                    "text": (
                        f"'{deleted_name}' {deleted_amount:,.0f}원 지출을 삭제했습니다."
                        f" 총 지출: {total_spent:,.0f}원"
                    )
                },
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "지출 삭제 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"지출 삭제 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_list_expenses(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Query all expenses for the current saved plan and emit expense_list event."""
        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "working", "message": "지출 항목 전체 조회 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is None or plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "budget_analyst", "status": "error", "message": "조회할 여행 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "지출 목록을 확인하려면 먼저 여행 계획을 저장해주세요."},
            }
            return

        try:
            from app.models import Expense as ExpenseModel, TravelPlan as TravelPlanModel

            plan = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "budget_analyst", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                }
                return

            all_expenses = (
                db.query(ExpenseModel)
                .filter(ExpenseModel.travel_plan_id == plan_id)
                .order_by(ExpenseModel.id.asc())
                .all()
            )

            expense_list = [
                {
                    "id": e.id,
                    "name": e.name,
                    "amount": e.amount,
                    "category": e.category,
                    "date": e.date.isoformat() if e.date else None,
                    "travel_plan_id": plan_id,
                }
                for e in all_expenses
            ]
            total_spent = round(sum(e.amount for e in all_expenses), 2)

            expense_count = len(all_expenses)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "budget_analyst",
                    "status": "done",
                    "message": f"{expense_count}개 지출 항목 조회 완료",
                    "result_count": expense_count,
                },
            }
            yield {
                "type": "expense_list",
                "data": {
                    "plan_id": plan_id,
                    "expenses": expense_list,
                    "total_spent": total_spent,
                    "expense_count": expense_count,
                },
            }

            if all_expenses:
                lines = [f"  • {e.name}: {e.amount:,.0f}원" for e in all_expenses]
                text = f"지출 항목 {expense_count}개 (합계: {total_spent:,.0f}원):\n" + "\n".join(lines)
            else:
                text = "아직 기록된 지출 항목이 없습니다."

            yield {"type": "chat_chunk", "data": {"text": text}}

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "budget_analyst", "status": "error", "message": "지출 목록 조회 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"지출 목록 조회 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_copy_plan(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Duplicate a saved travel plan and emit plan_saved event with the new plan data."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "여행 계획 복사 중..."},
        }
        await asyncio.sleep(0)

        if db is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "DB가 연결되지 않았습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "여행 계획을 복사하려면 DB 연결이 필요합니다."},
            }
            return

        try:
            from app.models import DayItinerary as DayItineraryModel, Place as PlaceModel, TravelPlan as TravelPlanModel

            original: Optional[TravelPlanModel] = None

            # 1. Try exact ID lookup first (intent.plan_id or session's last saved plan)
            plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id
            if plan_id is not None:
                original = db.get(TravelPlanModel, plan_id)

            # 2. Fall back to destination substring search
            if original is None and intent.destination:
                original = (
                    db.query(TravelPlanModel)
                    .filter(TravelPlanModel.destination.ilike(f"%{intent.destination}%"))
                    .order_by(TravelPlanModel.created_at.desc())
                    .first()
                )

            if original is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": "복사할 계획을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": "복사할 여행 계획을 찾을 수 없습니다. 계획 ID나 목적지를 확인해주세요."},
                }
                return

            # Duplicate the plan (mirror of the /duplicate REST endpoint logic)
            copy = TravelPlanModel(
                destination=original.destination,
                start_date=original.start_date,
                end_date=original.end_date,
                budget=original.budget,
                interests=original.interests,
                notes=original.notes if hasattr(original, "notes") else None,
                tags=original.tags if hasattr(original, "tags") else None,
                status="draft",
            )
            db.add(copy)
            db.flush()

            for day in original.itineraries:
                day_copy = DayItineraryModel(
                    travel_plan_id=copy.id,
                    date=day.date,
                    notes=day.notes,
                    transport=day.transport,
                )
                db.add(day_copy)
                db.flush()

                for place in day.places:
                    db.add(PlaceModel(
                        day_itinerary_id=day_copy.id,
                        name=place.name,
                        category=place.category,
                        address=place.address,
                        estimated_cost=place.estimated_cost,
                        ai_reason=place.ai_reason,
                        order=place.order,
                    ))

            db.commit()
            db.refresh(copy)

            # Update session to point to the new copy
            session.last_saved_plan_id = copy.id

            new_plan_data = {
                "id": copy.id,
                "destination": copy.destination,
                "start_date": copy.start_date.isoformat() if copy.start_date else None,
                "end_date": copy.end_date.isoformat() if copy.end_date else None,
                "budget": copy.budget,
                "status": copy.status,
            }

            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "복사 완료!"},
            }
            yield {
                "type": "plan_saved",
                "data": {
                    "message": f"'{original.destination}' 여행 계획이 복사되었습니다.",
                    "plan_id": copy.id,
                    "plan": new_plan_data,
                    "copied_from": original.id,
                },
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"'{original.destination}' 여행 계획(#{original.id})이 복사되어 새 계획(#{copy.id})이 생성되었습니다."},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "계획 복사 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"여행 계획 복사 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_share_plan(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Generate a shareable link for the current or specified travel plan."""
        yield {
            "type": "agent_status",
            "data": {"agent": "secretary", "status": "working", "message": "공유 링크 생성 중..."},
        }
        await asyncio.sleep(0)

        if db is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "DB가 연결되지 않았습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "공유 링크를 생성하려면 DB 연결이 필요합니다."},
            }
            return

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id
        if plan_id is None:
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "저장된 계획이 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "공유할 여행 계획이 없습니다. 먼저 계획을 저장해주세요."},
            }
            return

        try:
            import secrets as _secrets

            from app.models import TravelPlan as TravelPlanModel

            plan: Optional[TravelPlanModel] = db.get(TravelPlanModel, plan_id)
            if plan is None:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "secretary", "status": "error", "message": "계획을 찾을 수 없습니다"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Plan #{plan_id}을 찾을 수 없습니다."},
                }
                return

            if not plan.is_shared or not plan.share_token:
                plan.share_token = _secrets.token_urlsafe(32)
                plan.is_shared = True
                db.commit()
                db.refresh(plan)

            import os as _os
            base_url = _os.getenv("APP_BASE_URL", "").rstrip("/")
            share_url = f"{base_url}/travel-plans/shared/{plan.share_token}"

            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "done", "message": "공유 링크 생성 완료!"},
            }
            yield {
                "type": "plan_shared",
                "data": {
                    "plan_id": plan.id,
                    "share_token": plan.share_token,
                    "share_url": share_url,
                },
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"공유 링크가 생성되었습니다: {share_url}"},
            }

        except Exception as exc:
            logger.error("_handle_share_plan: failed — %s: %s", type(exc).__name__, exc, exc_info=True)
            yield {
                "type": "agent_status",
                "data": {"agent": "secretary", "status": "error", "message": "공유 링크 생성 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"공유 링크 생성 중 오류가 발생했습니다: {exc}"},
            }

    async def _handle_reorder_days(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Swap the places of two days in the itinerary.

        Reads day_number and day_number_2 from intent. Swaps place lists between
        the two days in DB (if available) or in session.last_plan. Emits
        day_update for both days and a confirming chat_chunk. Returns an error
        chat_chunk when either day number is out of range or missing.
        """
        day_a = intent.day_number
        day_b = intent.day_number_2

        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": "일정 순서 변경 중..."},
        }
        await asyncio.sleep(0)

        if not day_a or not day_b:
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "error", "message": "교환할 두 날짜를 지정해주세요"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "교환할 두 날짜(예: '1일차와 3일차')를 알려주세요."},
            }
            return

        if day_a == day_b:
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "done", "message": "같은 날짜입니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"Day {day_a}와 Day {day_b}는 동일한 날짜입니다."},
            }
            return

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is not None and plan_id is not None:
            try:
                from app.models import (
                    DayItinerary as DayItineraryModel,
                    TravelPlan as TravelPlanModel,
                )

                plan = db.get(TravelPlanModel, plan_id)
                if plan is None:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                    }
                    return

                days = (
                    db.query(DayItineraryModel)
                    .filter(DayItineraryModel.travel_plan_id == plan_id)
                    .order_by(DayItineraryModel.date)
                    .all()
                )

                total = len(days)
                if day_a < 1 or day_a > total or day_b < 1 or day_b > total:
                    out = day_a if (day_a < 1 or day_a > total) else day_b
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"Day {out}이 범위를 벗어났습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {out}은 이 계획에 없습니다 (총 {total}일)."},
                    }
                    return

                day_obj_a = days[day_a - 1]
                day_obj_b = days[day_b - 1]

                # Swap day_itinerary_id of all places between the two days
                places_a = list(day_obj_a.places)
                places_b = list(day_obj_b.places)

                for p in places_a:
                    p.day_itinerary_id = day_obj_b.id
                for p in places_b:
                    p.day_itinerary_id = day_obj_a.id

                db.commit()
                db.refresh(day_obj_a)
                db.refresh(day_obj_b)

                def _day_data(day_obj: "DayItineraryModel", day_num: int) -> dict:
                    return {
                        "day_number": day_num,
                        "date": day_obj.date.isoformat(),
                        "notes": day_obj.notes,
                        "transport": day_obj.transport,
                        "places": [
                            {
                                "name": p.name,
                                "category": p.category,
                                "address": p.address,
                                "estimated_cost": p.estimated_cost,
                                "ai_reason": p.ai_reason,
                                "order": p.order,
                            }
                            for p in sorted(day_obj.places, key=lambda x: x.order)
                        ],
                    }

                yield {"type": "day_update", "data": _day_data(day_obj_a, day_a)}
                yield {"type": "day_update", "data": _day_data(day_obj_b, day_b)}
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "done", "message": f"Day {day_a}와 Day {day_b} 교환 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_a}와 Day {day_b}의 일정을 교환했습니다."},
                }

            except Exception as exc:
                logger.error("_handle_reorder_days: failed — %s: %s", type(exc).__name__, exc, exc_info=True)
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "error", "message": "일정 순서 변경 실패"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"일정 순서 변경 중 오류가 발생했습니다: {exc}"},
                }
        else:
            # In-memory plan swap
            last_plan = session.last_plan
            if last_plan:
                days = last_plan.get("days", [])
                total = len(days)
                if day_a < 1 or day_a > total or day_b < 1 or day_b > total:
                    out = day_a if (day_a < 1 or day_a > total) else day_b
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"Day {out}이 범위를 벗어났습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {out}은 이 계획에 없습니다 (총 {total}일)."},
                    }
                    return

                day_obj_a = days[day_a - 1]
                day_obj_b = days[day_b - 1]

                # Swap places between the two day dicts
                places_a = day_obj_a.get("places", [])
                places_b = day_obj_b.get("places", [])
                day_obj_a["places"] = places_b
                day_obj_b["places"] = places_a

                yield {"type": "day_update", "data": {**day_obj_a, "day_number": day_a}}
                yield {"type": "day_update", "data": {**day_obj_b, "day_number": day_b}}
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "done", "message": f"Day {day_a}와 Day {day_b} 교환 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_a}와 Day {day_b}의 일정을 교환했습니다 (미저장 — 저장 후 영구 보관됩니다)."},
                }
                return

            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "done", "message": "일정 교환 완료"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "일정을 교환하려면 먼저 여행 계획을 만들거나 저장해주세요."},
            }

    async def _handle_clear_day(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Remove ALL places from a specific day in the itinerary.

        Reads day_number from intent. Deletes all Place rows for that day from DB
        (if available) or empties the places list in session.last_plan. Emits
        day_update with an empty places list and a confirming chat_chunk.
        Returns an error chat_chunk when day_number is missing or out of range.
        """
        day_number = intent.day_number

        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": "일정 초기화 중..."},
        }
        await asyncio.sleep(0)

        if not day_number:
            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "error", "message": "초기화할 날짜를 지정해주세요"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "초기화할 날짜(예: '3일차')를 알려주세요."},
            }
            return

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is not None and plan_id is not None:
            try:
                from app.models import (
                    DayItinerary as DayItineraryModel,
                    Place as PlaceModel,
                    TravelPlan as TravelPlanModel,
                )

                plan = db.get(TravelPlanModel, plan_id)
                if plan is None:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                    }
                    return

                days = (
                    db.query(DayItineraryModel)
                    .filter(DayItineraryModel.travel_plan_id == plan_id)
                    .order_by(DayItineraryModel.date)
                    .all()
                )

                total = len(days)
                if day_number < 1 or day_number > total:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"Day {day_number}이 범위를 벗어났습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {day_number}은 이 계획에 없습니다 (총 {total}일)."},
                    }
                    return

                day_obj = days[day_number - 1]

                # Delete all places for this day
                db.query(PlaceModel).filter(PlaceModel.day_itinerary_id == day_obj.id).delete()
                db.commit()
                db.refresh(day_obj)

                yield {
                    "type": "day_update",
                    "data": {
                        "day_number": day_number,
                        "date": day_obj.date.isoformat(),
                        "notes": day_obj.notes,
                        "transport": day_obj.transport,
                        "places": [],
                    },
                }
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "done", "message": f"Day {day_number} 일정 초기화 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_number}의 모든 장소를 삭제했습니다."},
                }

            except Exception as exc:
                logger.error("_handle_clear_day: failed — %s: %s", type(exc).__name__, exc, exc_info=True)
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "error", "message": "일정 초기화 실패"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"일정 초기화 중 오류가 발생했습니다: {exc}"},
                }
        else:
            # In-memory plan clear
            last_plan = session.last_plan
            if last_plan:
                days = last_plan.get("days", [])
                total = len(days)
                if day_number < 1 or day_number > total:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"Day {day_number}이 범위를 벗어났습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {day_number}은 이 계획에 없습니다 (총 {total}일)."},
                    }
                    return

                day_obj = days[day_number - 1]
                day_obj["places"] = []

                yield {"type": "day_update", "data": {**day_obj, "day_number": day_number}}
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "done", "message": f"Day {day_number} 일정 초기화 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_number}의 모든 장소를 삭제했습니다 (미저장 — 저장 후 영구 보관됩니다)."},
                }
                return

            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "done", "message": "일정 초기화 완료"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "일정을 초기화하려면 먼저 여행 계획을 만들거나 저장해주세요."},
            }

    async def _handle_get_weather(
        self,
        intent: Intent,
        session: "ChatSession",
    ) -> AsyncGenerator[dict, None]:
        """Fetch weather forecast for the trip destination and dates."""
        dest = intent.destination or (session.last_plan or {}).get("destination") or "목적지"
        start, end = self._parse_dates(intent, require=True)
        start_str = start.isoformat()
        end_str = end.isoformat()

        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "working", "message": f"{dest} 날씨 조회 중..."},
        }

        try:
            result = await asyncio.to_thread(
                self._web_search.search_weather,
                dest,
                start_str,
                end_str,
            )

            forecast_count = len(result.forecast)
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "place_scout",
                    "status": "done",
                    "message": f"날씨 정보 조회 완료 ({forecast_count}일)",
                    "result_count": forecast_count,
                },
            }
            yield {
                "type": "search_results",
                "data": {"type": "weather", "results": result.model_dump()},
            }
            yield {
                "type": "weather_data",
                "data": result.model_dump(),
            }
            summary_text = result.summary or f"{dest} 날씨 정보를 가져왔습니다."
            yield {
                "type": "chat_chunk",
                "data": {"text": summary_text},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "place_scout", "status": "error", "message": "날씨 조회 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"날씨 조회 중 오류가 발생했습니다: {exc}"},
            }


    async def _handle_add_day_note(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Append a note to a specific day's itinerary."""
        day_number = intent.day_number or 1
        note_text = intent.query or intent.raw_message

        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "thinking", "message": f"Day {day_number} 노트 추가 준비 중..."},
        }
        await asyncio.sleep(0)
        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": f"Day {day_number}에 노트 추가 중..."},
        }

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is not None and plan_id is not None:
            try:
                from app.models import (
                    DayItinerary as DayItineraryModel,
                    TravelPlan as TravelPlanModel,
                )

                plan = db.get(TravelPlanModel, plan_id)
                if plan is None:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                    }
                    return

                days = (
                    db.query(DayItineraryModel)
                    .filter(DayItineraryModel.travel_plan_id == plan_id)
                    .order_by(DayItineraryModel.date)
                    .all()
                )

                day_index = day_number - 1
                if not days or day_index >= len(days) or day_index < 0:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"Day {day_number}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획에 Day {day_number}이 없습니다."},
                    }
                    return

                day = days[day_index]
                separator = "\n" if day.notes else ""
                day.notes = day.notes + separator + note_text
                db.commit()
                db.refresh(day)

                places_data = [
                    {
                        "name": p.name,
                        "category": p.category,
                        "address": p.address,
                        "estimated_cost": p.estimated_cost,
                        "ai_reason": p.ai_reason,
                        "order": p.order,
                    }
                    for p in sorted(day.places, key=lambda x: x.order)
                ]
                day_data = {
                    "day_number": day_number,
                    "date": day.date.isoformat(),
                    "notes": day.notes,
                    "transport": day.transport,
                    "places": places_data,
                }

                yield {"type": "day_update", "data": day_data}
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "done", "message": f"Day {day_number} 노트 추가 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_number}에 노트를 추가했습니다: {note_text}"},
                }

            except Exception as exc:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "error", "message": "노트 추가 실패"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"노트 추가 중 오류가 발생했습니다: {exc}"},
                }
        else:
            # No saved plan in DB — update in-memory last_plan if available
            last_plan = session.last_plan
            if last_plan:
                days = last_plan.get("days", [])
                day_index = day_number - 1
                if 0 <= day_index < len(days):
                    day = days[day_index]
                    existing_notes = day.get("notes", "")
                    separator = "\n" if existing_notes else ""
                    day["notes"] = existing_notes + separator + note_text
                    yield {"type": "day_update", "data": day}
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "done", "message": f"Day {day_number} 노트 추가 완료!"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {day_number}에 노트를 추가했습니다 (미저장 — 저장 후 영구 보관됩니다)."},
                    }
                    return

            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "done", "message": f"Day {day_number} 노트 추가 완료!"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "노트를 추가하려면 먼저 여행 계획을 만들거나 저장해주세요."},
            }

    async def _handle_remove_place(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Remove a place from a specific day's itinerary.

        Matches by place name (query, partial case-insensitive) or 1-based index
        (place_index). Emits day_update after removal. Graceful fallback when no
        plan exists or place is not found.
        """
        day_number = intent.day_number or 1
        place_name = intent.query
        place_index = intent.place_index  # 1-based

        yield {
            "type": "agent_status",
            "data": {"agent": "planner", "status": "working", "message": f"Day {day_number}에서 장소 제거 중..."},
        }
        await asyncio.sleep(0)

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is not None and plan_id is not None:
            try:
                from app.models import (
                    DayItinerary as DayItineraryModel,
                    TravelPlan as TravelPlanModel,
                )

                plan = db.get(TravelPlanModel, plan_id)
                if plan is None:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                    }
                    return

                days = (
                    db.query(DayItineraryModel)
                    .filter(DayItineraryModel.travel_plan_id == plan_id)
                    .order_by(DayItineraryModel.date)
                    .all()
                )

                day_idx = day_number - 1
                if not days or day_idx >= len(days) or day_idx < 0:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"Day {day_number}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획에 Day {day_number}이 없습니다."},
                    }
                    return

                day = days[day_idx]
                places = sorted(day.places, key=lambda x: x.order)

                target_place = None
                if place_name:
                    name_lower = place_name.lower()
                    for p in places:
                        if name_lower in p.name.lower():
                            target_place = p
                            break
                elif place_index is not None:
                    actual_idx = len(places) + place_index if place_index < 0 else place_index - 1
                    if 0 <= actual_idx < len(places):
                        target_place = places[actual_idx]
                elif places:
                    target_place = places[0]

                if target_place is None:
                    not_found = place_name or (f"#{place_index}" if place_index else "장소")
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "planner", "status": "error", "message": f"'{not_found}' 장소를 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {day_number}에서 '{not_found}'을 찾을 수 없습니다."},
                    }
                    return

                removed_name = target_place.name
                db.delete(target_place)
                db.commit()
                db.refresh(day)

                places_data = [
                    {
                        "name": p.name,
                        "category": p.category,
                        "address": p.address,
                        "estimated_cost": p.estimated_cost,
                        "ai_reason": p.ai_reason,
                        "order": p.order,
                    }
                    for p in sorted(day.places, key=lambda x: x.order)
                ]
                day_data = {
                    "day_number": day_number,
                    "date": day.date.isoformat(),
                    "notes": day.notes,
                    "transport": day.transport,
                    "places": places_data,
                }

                yield {"type": "day_update", "data": day_data}
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "done", "message": f"Day {day_number}에서 '{removed_name}' 제거 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_number}에서 '{removed_name}'을 제거했습니다."},
                }

            except Exception as exc:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "planner", "status": "error", "message": "장소 제거 실패"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"장소 제거 중 오류가 발생했습니다: {exc}"},
                }
        else:
            # In-memory plan update
            last_plan = session.last_plan
            if last_plan:
                days = last_plan.get("days", [])
                day_idx = day_number - 1
                if 0 <= day_idx < len(days):
                    day = days[day_idx]
                    places = day.get("places", [])

                    target_idx = None
                    if place_name:
                        name_lower = place_name.lower()
                        for i, p in enumerate(places):
                            if name_lower in p.get("name", "").lower():
                                target_idx = i
                                break
                    elif place_index is not None:
                        actual_idx = len(places) + place_index if place_index < 0 else place_index - 1
                        if 0 <= actual_idx < len(places):
                            target_idx = actual_idx
                    elif places:
                        target_idx = 0

                    if target_idx is not None:
                        removed = places.pop(target_idx)
                        removed_name = removed.get("name", "장소")
                        yield {"type": "day_update", "data": day}
                        yield {
                            "type": "agent_status",
                            "data": {"agent": "planner", "status": "done", "message": f"Day {day_number}에서 '{removed_name}' 제거 완료!"},
                        }
                        yield {
                            "type": "chat_chunk",
                            "data": {"text": f"Day {day_number}에서 '{removed_name}'을 제거했습니다 (미저장 — 저장 후 영구 보관됩니다)."},
                        }
                        return
                    else:
                        not_found = place_name or (f"#{place_index}" if place_index else "장소")
                        yield {
                            "type": "agent_status",
                            "data": {"agent": "planner", "status": "error", "message": f"'{not_found}' 장소를 찾을 수 없습니다"},
                        }
                        yield {
                            "type": "chat_chunk",
                            "data": {"text": f"Day {day_number}에서 '{not_found}'을 찾을 수 없습니다."},
                        }
                        return

            yield {
                "type": "agent_status",
                "data": {"agent": "planner", "status": "done", "message": "장소 제거 완료"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "장소를 제거하려면 먼저 여행 계획을 만들거나 저장해주세요."},
            }

    async def _handle_add_place(
        self,
        intent: Intent,
        session: "ChatSession",
        db: Optional["Session"] = None,
    ) -> AsyncGenerator[dict, None]:
        """Append a custom place to a specific day's itinerary.

        Extracts day_number + place name (query) + optional category (place_category).
        Emits place_scout working→done and day_update. Graceful fallback when no plan.
        """
        day_number = intent.day_number or 1
        place_name = intent.query or ""
        category = intent.place_category or "sightseeing"

        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "working", "message": f"Day {day_number}에 장소 추가 중..."},
        }
        await asyncio.sleep(0)

        if not place_name:
            yield {
                "type": "agent_status",
                "data": {"agent": "place_scout", "status": "error", "message": "추가할 장소 이름을 알 수 없습니다"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "추가할 장소 이름을 알려주세요."},
            }
            return

        plan_id: Optional[int] = intent.plan_id or session.last_saved_plan_id

        if db is not None and plan_id is not None:
            try:
                from app.models import (
                    DayItinerary as DayItineraryModel,
                    Place as PlaceModel,
                    TravelPlan as TravelPlanModel,
                )

                plan = db.get(TravelPlanModel, plan_id)
                if plan is None:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "place_scout", "status": "error", "message": f"계획 #{plan_id}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획 #{plan_id}을 찾을 수 없습니다."},
                    }
                    return

                days = (
                    db.query(DayItineraryModel)
                    .filter(DayItineraryModel.travel_plan_id == plan_id)
                    .order_by(DayItineraryModel.date)
                    .all()
                )

                day_idx = day_number - 1
                if not days or day_idx >= len(days) or day_idx < 0:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "place_scout", "status": "error", "message": f"Day {day_number}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획에 Day {day_number}이 없습니다."},
                    }
                    return

                day = days[day_idx]
                next_order = max((p.order for p in day.places), default=-1) + 1
                new_place = PlaceModel(
                    day_itinerary_id=day.id,
                    name=place_name,
                    category=category,
                    estimated_cost=0.0,
                    order=next_order,
                )
                db.add(new_place)
                db.commit()
                db.refresh(day)

                places_data = [
                    {
                        "name": p.name,
                        "category": p.category,
                        "address": p.address,
                        "estimated_cost": p.estimated_cost,
                        "ai_reason": p.ai_reason,
                        "order": p.order,
                    }
                    for p in sorted(day.places, key=lambda x: x.order)
                ]
                day_data = {
                    "day_number": day_number,
                    "date": day.date.isoformat(),
                    "notes": day.notes,
                    "transport": day.transport,
                    "places": places_data,
                }

                yield {"type": "day_update", "data": day_data}
                yield {
                    "type": "agent_status",
                    "data": {"agent": "place_scout", "status": "done", "message": f"Day {day_number}에 '{place_name}' 추가 완료!"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"Day {day_number}에 '{place_name}'을 추가했습니다."},
                }

            except Exception as exc:
                yield {
                    "type": "agent_status",
                    "data": {"agent": "place_scout", "status": "error", "message": "장소 추가 실패"},
                }
                yield {
                    "type": "chat_chunk",
                    "data": {"text": f"장소 추가 중 오류가 발생했습니다: {exc}"},
                }
        else:
            # In-memory plan update
            last_plan = session.last_plan
            if last_plan:
                days = last_plan.get("days", [])
                day_idx = day_number - 1
                if 0 <= day_idx < len(days):
                    day = days[day_idx]
                    places = day.get("places", [])
                    new_place = {
                        "name": place_name,
                        "category": category,
                        "address": "",
                        "estimated_cost": 0.0,
                        "ai_reason": "",
                        "order": len(places),
                    }
                    places.append(new_place)
                    day["places"] = places

                    yield {"type": "day_update", "data": day}
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "place_scout", "status": "done", "message": f"Day {day_number}에 '{place_name}' 추가 완료!"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"Day {day_number}에 '{place_name}'을 추가했습니다 (미저장 — 저장 후 영구 보관됩니다)."},
                    }
                    return
                else:
                    yield {
                        "type": "agent_status",
                        "data": {"agent": "place_scout", "status": "error", "message": f"Day {day_number}을 찾을 수 없습니다"},
                    }
                    yield {
                        "type": "chat_chunk",
                        "data": {"text": f"계획에 Day {day_number}이 없습니다."},
                    }
                    return

            yield {
                "type": "agent_status",
                "data": {"agent": "place_scout", "status": "done", "message": "장소 추가 완료"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": "장소를 추가하려면 먼저 여행 계획을 만들거나 저장해주세요."},
            }

    @staticmethod
    def _parse_suggestions(text: str) -> list[str]:
        """Parse numbered/bulleted suggestions from AI text into a list of strings."""
        suggestions: list[str] = []
        current: list[str] = []
        for line in text.strip().split("\n"):
            stripped = line.strip()
            if not stripped:
                if current:
                    suggestions.append(" ".join(current).strip())
                    current = []
                continue
            # New numbered item (e.g. "1. " or "1) ")
            if re.match(r"^\d+[.)]\s", stripped):
                if current:
                    suggestions.append(" ".join(current).strip())
                    current = []
                current = [re.sub(r"^\d+[.)]\s+", "", stripped)]
            # New bullet item (-, *, •)
            elif re.match(r"^[-*•]\s", stripped):
                if current:
                    suggestions.append(" ".join(current).strip())
                    current = []
                current = [re.sub(r"^[-*•]\s+", "", stripped)]
            else:
                current.append(stripped)
        if current:
            suggestions.append(" ".join(current).strip())
        return [s for s in suggestions if s]

    async def _handle_suggest_improvements(
        self,
        intent: Intent,
        session: "ChatSession",
    ) -> AsyncGenerator[dict, None]:
        """Ask Gemini to review the current plan + conversation history and suggest improvements.

        Read-only: does not modify the plan.
        Activates place_scout and budget_analyst for analysis.
        """
        yield {
            "type": "agent_status",
            "data": {"agent": "place_scout", "status": "thinking", "message": "장소 개선 아이디어 분석 중..."},
        }
        yield {
            "type": "agent_status",
            "data": {"agent": "budget_analyst", "status": "thinking", "message": "예산 최적화 분석 중..."},
        }

        current_plan = session.last_plan or {}
        history = list(session.message_history)

        try:
            stream = await asyncio.to_thread(
                self._gemini.suggest_improvements_stream,
                current_plan,
                history,
            )

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "place_scout",
                    "status": "done",
                    "message": "장소 분석 완료",
                },
            }
            yield {
                "type": "agent_status",
                "data": {
                    "agent": "budget_analyst",
                    "status": "done",
                    "message": "예산 분석 완료",
                },
            }

            # Stream suggestion text chunk by chunk
            full_text = ""
            for chunk in stream:
                if chunk.text:
                    full_text += chunk.text
                    yield {"type": "chat_chunk", "data": {"text": chunk.text}}

            suggestions = full_text or "개선 제안을 생성하지 못했습니다."
            parsed = self._parse_suggestions(suggestions)
            yield {
                "type": "plan_suggestions",
                "data": {"suggestions": parsed, "raw": suggestions},
            }

        except Exception as exc:
            yield {
                "type": "agent_status",
                "data": {"agent": "place_scout", "status": "error", "message": "분석 실패"},
            }
            yield {
                "type": "agent_status",
                "data": {"agent": "budget_analyst", "status": "error", "message": "분석 실패"},
            }
            yield {
                "type": "chat_chunk",
                "data": {"text": f"개선 제안 생성 중 오류가 발생했습니다: {exc}"},
            }

    # ------------------------------------------------------------------
    # General conversation handler
    # ------------------------------------------------------------------

    async def _handle_general(
        self,
        intent: Intent,
        session: "ChatSession",
    ) -> AsyncGenerator[dict, None]:
        """Handle 'general' intent: natural conversation with progressive
        travel-info extraction.  When all key fields (destination, dates, budget)
        are gathered, auto-delegates to ``_handle_create_plan``.

        Works in two modes:
        - **With API key**: calls Gemini for a contextual conversational response
          plus structured travel-info extraction.
        - **Without API key**: builds a context-aware fallback that avoids
          repeating the same question and acknowledges already-known info.
        """
        if self._api_key:
            async for event in self._general_with_gemini(intent, session):
                yield event
        else:
            async for event in self._general_fallback(intent, session):
                yield event

    async def _general_with_gemini(
        self,
        intent: Intent,
        session: "ChatSession",
    ) -> AsyncGenerator[dict, None]:
        """Gemini-powered general conversation handler with streaming."""
        history_lines = []
        for entry in session.message_history[-(_MAX_HISTORY_TURNS * 2):]:
            role = entry.get("role", "user").capitalize()
            content = entry.get("content", "")
            history_lines.append(f"{role}: {content}")
        history_str = "\n".join(history_lines) if history_lines else "(없음)"

        today_str = date.today().isoformat()
        current_year = date.today().year

        # Phase 1: Stream the conversational reply (plain text, no JSON)
        chat_prompt = (
            "You are a warm, enthusiastic travel consultant who genuinely loves helping people plan trips.\n"
            "Think of yourself as a friend who happens to be a travel expert — someone who gets excited about their trip ideas, "
            "shares personal-feeling recommendations, and builds up the journey together step by step.\n\n"
            f"Today's date is {today_str}. The current year is {current_year}.\n"
            "The user is based in South Korea. Use KRW (Korean Won) for all budget/cost values.\n\n"
            "Conversation so far:\n"
            f"{history_str}\n\n"
            f"User just said: \"{intent.raw_message}\"\n\n"
            "How to respond:\n"
            "- ALWAYS respond in the same language the user uses (Korean → Korean, English → English).\n"
            "- Be conversational and warm, like chatting with a friend. Use casual-polite tone (해요체) in Korean.\n"
            "- When the user shares a destination or preference, react with genuine enthusiasm and add a small insider tip or fun fact.\n"
            "  Example: '방콕이요! 좋은 선택이에요~ 요즘 카오산로드보다 탈랏롯파이 야시장이 훨씬 핫하거든요 🔥'\n"
            "- Build up the trip gradually. Don't rush to collect all info at once.\n"
            "  If one thing is missing, weave the question naturally into the conversation.\n"
            "  Bad: '일정을 알려주세요.' Good: '혹시 며칠 정도 다녀오실 생각이세요? 3박이면 알차게 돌 수 있고, 5박이면 여유롭게 즐길 수 있어요~'\n"
            "- When suggesting or acknowledging budget, frame it helpfully.\n"
            "  Example: '150만원이면 동남아 3박은 꽤 여유로운 편이에요! 맛집 투어도 충분히 가능하고요 😊'\n"
            "- Keep responses concise (2-4 sentences). Don't monologue.\n"
            "- If the user is just chatting casually, be friendly and naturally steer toward travel.\n"
        )

        try:
            client = genai.Client(api_key=self._api_key)

            # Stream text chunks to the client in real-time
            full_reply = ""
            with LLMTimer() as stream_timer:
                stream = await asyncio.to_thread(
                    client.models.generate_content_stream,
                    model="gemini-3-flash-preview",
                    contents=chat_prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(thinking_level="medium"),
                    ),
                )
                for chunk in stream:
                    if chunk.text:
                        full_reply += chunk.text
                        yield {"type": "chat_chunk", "data": {"text": chunk.text}}
            log_llm_call(
                caller="_general_with_gemini.stream",
                model="gemini-3-flash-preview",
                prompt=chat_prompt,
                response_text=full_reply,
                latency_ms=stream_timer.elapsed_ms,
                streaming=True,
            )

            if not full_reply.strip():
                yield {"type": "chat_chunk", "data": {"text": "죄송합니다, 응답을 생성하지 못했어요."}}
                return

            # Phase 2: Extract travel fields from conversation (lightweight JSON call)
            extract_prompt = (
                f"Today's date is {today_str}. Current year is {current_year}.\n"
                "The user is based in South Korea. Budget values are in KRW.\n"
                "From the conversation below, extract any travel planning details mentioned so far.\n\n"
                f"Conversation history:\n{history_str}\n\n"
                f"User's latest message: \"{intent.raw_message}\"\n"
                f"Assistant's reply: \"{full_reply[:500]}\"\n\n"
                "Return a JSON object with ALL fields (use null if unknown):\n"
                '{"destination": "city or null", "start_date": "YYYY-MM-DD or null",'
                ' "end_date": "YYYY-MM-DD or null", "budget": number_or_null,'
                ' "interests": "comma-separated or null",'
                ' "travel_style": "힐링/액티비티/맛집/문화/쇼핑 or null",'
                ' "companions": "혼자/커플/가족/친구/부모님 or null",'
                ' "preferences": ["free-form preference strings"] or null,'
                ' "departure_city": "departure city or null"}'
            )
            with LLMTimer() as extract_timer:
                extract_resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-3-flash-preview",
                    contents=extract_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        thinking_config=types.ThinkingConfig(thinking_level="medium"),
                    ),
                )
            result = json.loads(extract_resp.text)
            log_llm_call(
                caller="_general_with_gemini.extract",
                model="gemini-3-flash-preview",
                prompt=extract_prompt,
                response_text=extract_resp.text,
                latency_ms=extract_timer.elapsed_ms,
                extra={"extracted_fields": result},
            )

            # Merge extracted fields into session plan_context (progressive memory)
            ctx = session.plan_context or {}
            for key, val in result.items():
                if val is not None and val != "" and val != []:
                    ctx[key] = val
            session.plan_context = ctx
            yield {"type": "plan_context", "data": ctx}

            dest = result.get("destination")
            start = result.get("start_date")
            end = result.get("end_date")
            budget = result.get("budget")

            if dest and start and end and budget:
                pending = {
                    "destination": dest,
                    "start_date": start,
                    "end_date": end,
                    "budget": float(budget),
                    "interests": result.get("interests") or "",
                }
                session.pending_plan = pending
                yield {"type": "confirm_plan", "data": pending}

        except Exception as exc:
            logger.error("_general_with_gemini: Gemini call failed — %s: %s", type(exc).__name__, exc, exc_info=True)
            async for event in self._general_fallback(intent, session):
                yield event

    async def _general_fallback(
        self,
        intent: Intent,
        session: "ChatSession",
    ) -> AsyncGenerator[dict, None]:
        """Context-aware fallback when Gemini is unavailable.

        Avoids repeating the same question by tracking what info we already
        know from the intent and conversation history.
        """
        known: dict[str, str] = {}
        missing: list[str] = []

        # Check what we already know from intent fields
        if intent.destination:
            known["destination"] = intent.destination
        if intent.start_date:
            known["start_date"] = intent.start_date
        if intent.end_date:
            known["end_date"] = intent.end_date
        if intent.budget:
            known["budget"] = str(intent.budget)

        # Also scan message_history for previously mentioned info
        for entry in session.message_history:
            content = entry.get("content", "")
            content_lower = content.lower()
            if not known.get("destination"):
                for kw in ["일본", "도쿄", "오사카", "파리", "런던", "뉴욕", "방콕",
                            "하와이", "제주", "발리", "로마", "바르셀로나"]:
                    if kw in content_lower:
                        known["destination"] = kw
                        break
            if not known.get("budget"):
                # Match patterns like "200만원", "100만원", "50만 원"
                m = re.search(r"(\d+)\s*만\s*원", content)
                if m:
                    known["budget"] = str(int(m.group(1)) * 10000)
                # Match patterns like "예산은 1500000" or "$3000"
                m2 = re.search(r"(\d{6,})", content)
                if not known.get("budget") and m2:
                    known["budget"] = m2.group(1)

        # Determine what's still missing
        if "destination" not in known:
            missing.append("destination")
        if "start_date" not in known:
            missing.append("dates")
        if "budget" not in known:
            missing.append("budget")

        # Build a contextual response
        if known and not missing:
            # Have everything — emit confirm_plan for user confirmation
            dest = known["destination"]
            pending = {
                "destination": dest,
                "start_date": known.get("start_date"),
                "end_date": known.get("end_date"),
                "budget": float(known["budget"]),
                "interests": intent.interests or "",
            }
            session.pending_plan = pending
            yield {"type": "chat_chunk", "data": {
                "text": f"좋아요! {dest} 여행 조건을 정리해봤어요~ 한번 확인해주세요!",
            }}
            yield {"type": "confirm_plan", "data": pending}
            return

        # Emit plan_context with whatever we know so far
        if known:
            ctx = session.plan_context or {}
            for key, val in known.items():
                if val:
                    ctx[key] = val
            session.plan_context = ctx
            yield {"type": "plan_context", "data": ctx}

        # Build acknowledgment of known info + ask for ONE missing piece
        parts = []
        if known.get("destination"):
            parts.append(f"{known['destination']} 여행")
        if known.get("start_date"):
            parts.append(f"{known['start_date']} 출발")
        if known.get("budget"):
            parts.append(f"예산 {known['budget']}원")

        ack = ""
        if parts:
            ack = ", ".join(parts) + "이시군요! "

        # Ask for the FIRST missing piece only — conversationally
        question_map = {
            "destination": "어디로 떠나고 싶으세요? 요즘 마음에 두고 있는 곳이 있나요? 😊",
            "dates": "혹시 언제쯤 떠나실 생각이세요? 대략적으로라도 괜찮아요~",
            "budget": "예산은 어느 정도로 생각하고 계세요? 대략적인 범위만 알려주셔도 돼요!",
        }
        ask = question_map.get(missing[0], "") if missing else ""

        response_text = (ack + ask).strip()
        if not response_text:
            response_text = "어디로 떠나고 싶으세요? 요즘 마음에 두고 있는 곳이 있나요? 😊"

        yield {"type": "chat_chunk", "data": {"text": response_text}}

    async def _handle_reset_conversation(
        self, session: "ChatSession"
    ) -> AsyncGenerator[dict, None]:
        """Clear in-memory conversation history and emit session_reset event."""
        session.history.clear()
        session.message_history.clear()
        session.plan_context = None
        session.pending_plan = None
        yield {
            "type": "agent_status",
            "data": {"agent": "coordinator", "status": "done", "message": "대화 내역 초기화 완료"},
        }
        yield {
            "type": "session_reset",
            "data": {"message": "대화 내역이 초기화되었습니다."},
        }
        yield {
            "type": "chat_chunk",
            "data": {"text": "대화 내역을 초기화했습니다. 새로운 여행 계획을 시작해보세요!"},
        }


# Module-level singleton used by the chat router
chat_service = ChatService()
logger.info(
    "ChatService initialized — API key %s, model=gemini-3-flash-preview",
    "configured" if chat_service._api_key else "MISSING",
)
