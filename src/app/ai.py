from datetime import date

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import GEMINI_API_KEY


class AIPlace(BaseModel):
    name: str
    category: str = ""
    address: str = ""
    estimated_cost: float = 0.0
    ai_reason: str = ""


class AIDayItinerary(BaseModel):
    date: str  # YYYY-MM-DD
    notes: str = ""
    transport: str = ""
    places: list[AIPlace] = []


class AIItineraryResult(BaseModel):
    days: list[AIDayItinerary]
    total_estimated_cost: float = 0.0


class GeminiService:
    MODEL = "gemini-3-flash-preview"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or GEMINI_API_KEY

    def _build_prompt(
        self,
        destination: str,
        start_date: date,
        end_date: date,
        budget: float,
        interests: str,
    ) -> str:
        num_days = (end_date - start_date).days + 1
        interests_str = interests if interests else "sightseeing, food, culture"
        return f"""You are an expert travel planner. Create a detailed day-by-day itinerary.

Trip Details:
- Destination: {destination}
- Start Date: {start_date}
- End Date: {end_date}
- Duration: {num_days} days
- Budget: {budget:,.0f}원 (KRW) total
- Interests: {interests_str}

Instructions:
- Create exactly {num_days} days (one entry per day from {start_date} to {end_date})
- For each day, recommend 3-5 specific real places (attractions, restaurants, cafes, etc.)
- Include estimated costs per place in KRW (Korean Won)
- Keep total_estimated_cost within the {budget:,.0f}원 budget
- Provide a brief ai_reason why each place is recommended
- Use realistic transport options (walking, subway, taxi, bus)
- Each day's date field must be in YYYY-MM-DD format"""

    def generate_itinerary(
        self,
        destination: str,
        start_date: date,
        end_date: date,
        budget: float,
        interests: str = "",
    ) -> AIItineraryResult:
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        client = genai.Client(api_key=self._api_key)
        prompt = self._build_prompt(destination, start_date, end_date, budget, interests)

        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AIItineraryResult,
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
            ),
        )

        return AIItineraryResult.model_validate_json(response.text)

    def suggest_improvements(
        self,
        current_plan: dict,
        conversation_history: list[dict],
    ) -> str:
        """Review the current travel plan and conversation history, then return AI-powered improvement suggestions as plain text.

        Raises ValueError if no API key is configured.
        """
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        import json as _json

        plan_summary = _json.dumps(current_plan, indent=2, default=str) if current_plan else "No plan available yet."

        history_lines = []
        for entry in conversation_history[-20:]:  # last 10 turns
            role = entry.get("role", "user").capitalize()
            content = entry.get("content", "")
            history_lines.append(f"{role}: {content}")
        history_str = "\n".join(history_lines) if history_lines else "No conversation history."

        prompt = f"""You are an expert travel consultant reviewing a traveler's current plan.

Current Travel Plan:
{plan_summary}

Recent Conversation:
{history_str}

Please provide 3-5 concrete, actionable improvement suggestions for this travel plan. Focus on:
- Places that could be added or swapped for better experiences
- Budget optimization opportunities
- Logical day sequencing improvements
- Hidden gems or must-visit spots the traveler might have missed

Be specific, friendly, and concise. Respond in the same language the traveler used."""

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
            ),
        )

        return response.text or "개선 제안을 생성하지 못했습니다."

    def suggest_improvements_stream(
        self,
        current_plan: dict,
        conversation_history: list[dict],
    ):
        """Stream improvement suggestions chunk by chunk.

        Returns an iterator of text chunks (google-genai stream response).
        """
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        import json as _json

        plan_summary = _json.dumps(current_plan, indent=2, default=str) if current_plan else "No plan available yet."

        history_lines = []
        for entry in conversation_history[-20:]:
            role = entry.get("role", "user").capitalize()
            content = entry.get("content", "")
            history_lines.append(f"{role}: {content}")
        history_str = "\n".join(history_lines) if history_lines else "No conversation history."

        prompt = f"""You are an expert travel consultant reviewing a traveler's current plan.

Current Travel Plan:
{plan_summary}

Recent Conversation:
{history_str}

Please provide 3-5 concrete, actionable improvement suggestions for this travel plan. Focus on:
- Places that could be added or swapped for better experiences
- Budget optimization opportunities
- Logical day sequencing improvements
- Hidden gems or must-visit spots the traveler might have missed

Be specific, friendly, and concise. Respond in the same language the traveler used."""

        client = genai.Client(api_key=self._api_key)
        return client.models.generate_content_stream(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
            ),
        )

    def refine_itinerary(
        self,
        destination: str,
        start_date: date,
        end_date: date,
        budget: float,
        interests: str,
        current_days: list[dict],
        instruction: str,
    ) -> AIItineraryResult:
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        import json as _json

        num_days = (end_date - start_date).days + 1
        current_plan_str = _json.dumps(current_days, indent=2, default=str)

        prompt = f"""You are an expert travel planner. Refine the following existing travel itinerary based on the user's instruction.

Trip Details:
- Destination: {destination}
- Start Date: {start_date}
- End Date: {end_date}
- Duration: {num_days} days
- Budget: {budget:,.0f}원 (KRW) total
- Interests: {interests if interests else "sightseeing, food, culture"}

Current Itinerary:
{current_plan_str}

User's Refinement Instruction:
{instruction}

Instructions:
- Apply the user's instruction to update the itinerary
- Keep the same number of days ({num_days} days, {start_date} to {end_date})
- Maintain each day's date field in YYYY-MM-DD format
- Keep total_estimated_cost within the {budget:,.0f}원 budget
- Preserve unchanged days as-is; only modify days affected by the instruction
- Each place must have name, category, address, estimated_cost, and ai_reason"""

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AIItineraryResult,
                thinking_config=types.ThinkingConfig(thinking_level="medium"),
            ),
        )

        return AIItineraryResult.model_validate_json(response.text)
