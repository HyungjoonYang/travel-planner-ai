"""Hotel search service using Gemini with Google Search grounding."""
import json
import re

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import GEMINI_API_KEY


class HotelResult(BaseModel):
    name: str
    description: str = ""
    price_range: str = ""
    address: str = ""
    rating: str = ""
    amenities: list[str] = []
    tips: str = ""


class HotelSearchResult(BaseModel):
    destination: str
    check_in: str = ""
    check_out: str = ""
    budget_per_night: int = 0
    hotels: list[HotelResult]
    summary: str = ""


class HotelSearchService:
    MODEL = "gemini-2.0-flash"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or GEMINI_API_KEY

    def _build_search_prompt(
        self,
        destination: str,
        check_in: str = "",
        check_out: str = "",
        budget_per_night: int = 0,
        guests: int = 1,
    ) -> str:
        date_clause = ""
        if check_in and check_out:
            date_clause = f" for {check_in} to {check_out}"
        budget_clause = f" under ${budget_per_night}/night" if budget_per_night > 0 else ""
        guests_clause = f" for {guests} guest(s)" if guests > 1 else ""

        return f"""Search the web for top hotels in {destination}{date_clause}{budget_clause}{guests_clause}.

Return a JSON object with this exact structure:
{{
  "hotels": [
    {{
      "name": "Hotel name",
      "description": "Brief description of the hotel",
      "price_range": "Price range per night (e.g. $80-$120/night)",
      "address": "Hotel address or neighborhood",
      "rating": "Rating (e.g. 4.5/5 or 8.9/10)",
      "amenities": ["wifi", "breakfast", "pool"],
      "tips": "Booking tips or highlights"
    }}
  ],
  "summary": "Brief overview of accommodation options in {destination}"
}}

Return ONLY the JSON object, no markdown, no extra text."""

    def _extract_json(self, text: str) -> dict:
        """Extract a JSON object from text, handling markdown code fences."""
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            pass
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            return json.loads(fence_match.group(1))
        obj_match = re.search(r"\{.*\}", text, re.DOTALL)
        if obj_match:
            return json.loads(obj_match.group(0))
        raise ValueError(f"No valid JSON found in response: {text[:200]}")

    def search_hotels(
        self,
        destination: str,
        check_in: str = "",
        check_out: str = "",
        budget_per_night: int = 0,
        guests: int = 1,
    ) -> HotelSearchResult:
        """Search for hotels in a destination using Gemini with Google Search grounding."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        client = genai.Client(api_key=self._api_key)
        prompt = self._build_search_prompt(
            destination, check_in, check_out, budget_per_night, guests
        )

        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        data = self._extract_json(response.text)
        return HotelSearchResult(
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            budget_per_night=budget_per_night,
            hotels=data.get("hotels", []),
            summary=data.get("summary", ""),
        )
