import json
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
    MODEL = "gemini-2.0-flash"

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
- Budget: ${budget} USD total
- Interests: {interests_str}

Instructions:
- Create exactly {num_days} days (one entry per day from {start_date} to {end_date})
- For each day, recommend 3-5 specific real places (attractions, restaurants, cafes, etc.)
- Include estimated costs per place in USD
- Keep total estimated cost within the ${budget} budget
- Provide a brief reason why each place is recommended
- Use realistic transport options (walking, subway, taxi, bus)

Return a JSON object with this exact structure:
{{
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "notes": "Summary of the day",
      "transport": "Primary transport mode",
      "places": [
        {{
          "name": "Place name",
          "category": "sightseeing|food|cafe|hotel|activity|shopping",
          "address": "Full address",
          "estimated_cost": 0.0,
          "ai_reason": "Why this place is recommended"
        }}
      ]
    }}
  ],
  "total_estimated_cost": 0.0
}}"""

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
            ),
        )

        data = json.loads(response.text)
        return AIItineraryResult.model_validate(data)
