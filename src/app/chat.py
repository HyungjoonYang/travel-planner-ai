"""ChatService: session management + intent extraction + SSE agent-status events."""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, AsyncGenerator, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.ai import GeminiService
from app.calendar_service import CalendarService
from app.config import GEMINI_API_KEY
from app.flight_search import FlightSearchService
from app.hotel_search import HotelSearchService
from app.web_search import WebSearchService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.ai import AIItineraryResult

SESSION_TTL_SECONDS = 1800  # 30 minutes
_MAX_HISTORY_TURNS = 10     # max conversation turns kept in message_history

_DEFAULT_DEPARTURE = "Seoul"  # default origin for flight search


class Intent(BaseModel):
    action: str  # create_plan | modify_day | refine_plan | search_places | search_hotels | search_flights | save_plan | export_calendar | list_plans | delete_plan | view_plan | add_expense | update_plan | get_expense_summary | general
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: Optional[float] = None
    interests: Optional[str] = None
    day_number: Optional[int] = None
    plan_id: Optional[int] = None
    query: Optional[str] = None
    access_token: Optional[str] = None
    expense_name: Optional[str] = None
    expense_amount: Optional[float] = None
    expense_category: Optional[str] = None
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

            prompt = f"""You are a travel planner AI assistant. Analyze the user message and extract their intent.
{context_section}
User message: "{message}"

Return a JSON object with these fields:
- action: one of "create_plan", "modify_day", "refine_plan", "search_places", "search_hotels", "search_flights", "save_plan", "list_plans", "delete_plan", "view_plan", "add_expense", "update_plan", "get_expense_summary", "general"
- destination: destination city/country if mentioned or inferred from conversation context, else null
- start_date: start date in YYYY-MM-DD if mentioned or inferred from context, else null
- end_date: end date in YYYY-MM-DD if mentioned or inferred from context, else null
- budget: budget as a number if mentioned or inferred from context, else null
- interests: comma-separated interests if mentioned or inferred from context, else null
- day_number: specific day number if modifying a day, else null
- plan_id: integer plan ID if deleting, viewing, or updating a specific plan (e.g. "3번 계획 삭제" → 3, "3번 계획 수정" → 3), else null
- For update_plan: destination = new destination/title if user wants to rename, budget = new budget value, start_date/end_date = new dates
- query: search query string if searching, else null
- expense_name: expense item name if adding an expense (e.g. "식사", "택시", "입장료"), else null
- expense_amount: expense amount as a number if adding an expense (e.g. "5만원" → 50000, "$30" → 30), else null
- expense_category: expense category if adding an expense (e.g. "food", "transport", "accommodation", "activities"), infer from context, else null
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
            async for event in self._handle_create_plan(intent):
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
        elif intent.action == "update_plan":
            async for event in self._handle_update_plan(intent, session, db):
                yield _track_and_collect(event)
        elif intent.action == "get_expense_summary":
            async for event in self._handle_get_expense_summary(intent, session, db):
                yield _track_and_collect(event)
        else:
            _fallback_text = "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."
            assistant_chunks.append(_fallback_text)
            yield {
                "type": "chat_chunk",
                "data": {"text": _fallback_text},
            }

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

    def _parse_dates(self, intent: Intent) -> tuple[date, date]:
        """Parse start/end dates from intent, falling back to sensible defaults."""
        try:
            start = date.fromisoformat(intent.start_date) if intent.start_date else None
        except ValueError:
            start = None
        try:
            end = date.fromisoformat(intent.end_date) if intent.end_date else None
        except ValueError:
            end = None

        if start is None:
            start = date.today() + timedelta(days=30)
        if end is None:
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

    async def _handle_create_plan(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        budget = intent.budget or 2000.0
        interests = intent.interests or ""
        start, end = self._parse_dates(intent)

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
            result = await asyncio.to_thread(
                self._gemini.generate_itinerary,
                dest, start, end, budget, interests,
            )

            place_count = sum(len(day.places) for day in result.days)
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
                    "message": f"총 ${result.total_estimated_cost:.0f} 예산 배분 완료",
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

    async def _handle_search_hotels(self, intent: Intent) -> AsyncGenerator[dict, None]:
        dest = intent.destination or "목적지"
        start, end = self._parse_dates(intent)
        budget_per_night = int(intent.budget / (end - start).days) if intent.budget else 0

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
        start, end = self._parse_dates(intent)

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
                budget = last_plan.get("budget", intent.budget or 2000.0)
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
                    start = date.today() + timedelta(days=30)
                if end is None:
                    end = start + timedelta(days=3)
                current_days = last_plan.get("days", [])

                result = await asyncio.to_thread(
                    self._gemini.refine_itinerary,
                    dest, start, end, budget, intent.interests or "",
                    current_days,
                    f"Day {day_number}: {instruction}",
                )
            else:
                dest = intent.destination or "목적지"
                budget = intent.budget or 2000.0
                start, end = self._parse_dates(intent)

                result = await asyncio.to_thread(
                    self._gemini.generate_itinerary,
                    dest, start, end, budget, intent.interests or "",
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
                budget = last_plan.get("budget", intent.budget or 2000.0)
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
                    start = date.today() + timedelta(days=30)
                if end is None:
                    end = start + timedelta(days=3)
                current_days = last_plan.get("days", [])
                interests = last_plan.get("interests", intent.interests or "")

                result = await asyncio.to_thread(
                    self._gemini.refine_itinerary,
                    dest, start, end, float(budget), interests,
                    current_days,
                    instruction,
                )
            else:
                dest = intent.destination or "목적지"
                budget = intent.budget or 2000.0
                interests = intent.interests or ""
                start, end = self._parse_dates(intent)

                result = await asyncio.to_thread(
                    self._gemini.generate_itinerary,
                    dest, start, end, budget, interests,
                )

            place_count = sum(len(day.places) for day in result.days)
            breakdown = self._compute_budget_breakdown(result)

            yield {
                "type": "agent_status",
                "data": {
                    "agent": "budget_analyst",
                    "status": "done",
                    "message": f"총 ${result.total_estimated_cost:.0f} 예산 재배분 완료",
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
                budget = last_plan.get("budget", intent.budget or 2000.0)
                interests = last_plan.get("interests", intent.interests or "")
            else:
                dest = intent.destination or "여행 계획"
                start, end = self._parse_dates(intent)
                start_str = start.isoformat()
                end_str = end.isoformat()
                budget = intent.budget or 2000.0
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


# Module-level singleton used by the chat router
chat_service = ChatService()
