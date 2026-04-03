"""Web search service for destination research using Gemini with Google Search grounding."""
import json
import re

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import GEMINI_API_KEY


class PlaceSearchResult(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    address: str = ""
    tips: str = ""


class DestinationSearchResult(BaseModel):
    destination: str
    query: str
    places: list[PlaceSearchResult]
    summary: str = ""


class WebSearchService:
    MODEL = "gemini-3.0-flash"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or GEMINI_API_KEY

    def _build_search_prompt(
        self, destination: str, interests: str = "", category: str = ""
    ) -> str:
        interests_str = interests if interests else "sightseeing, food, culture"
        category_clause = f" focused on {category}" if category else ""
        return f"""Search the web for top places to visit in {destination}{category_clause}.
Consider interests: {interests_str}.

Return a JSON object with this exact structure:
{{
  "places": [
    {{
      "name": "Place name",
      "description": "Brief description",
      "category": "sightseeing|food|cafe|activity|shopping|hotel",
      "address": "Address or area",
      "tips": "Practical tips for visitors"
    }}
  ],
  "summary": "Brief overview of {destination} as a travel destination"
}}

Return ONLY the JSON object, no markdown, no extra text."""

    def _extract_json(self, text: str) -> dict:
        """Extract a JSON object from text, handling markdown code fences."""
        # Direct parse (ideal case: pure JSON)
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            pass
        # Strip markdown code fence
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            return json.loads(fence_match.group(1))
        # Bare JSON object anywhere in the text
        obj_match = re.search(r"\{.*\}", text, re.DOTALL)
        if obj_match:
            return json.loads(obj_match.group(0))
        raise ValueError(f"No valid JSON found in response: {text[:200]}")

    def search_places(
        self,
        destination: str,
        interests: str = "",
        category: str = "",
    ) -> DestinationSearchResult:
        """Search for places in a destination using Gemini with Google Search grounding."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        client = genai.Client(api_key=self._api_key)
        prompt = self._build_search_prompt(destination, interests, category)
        query = destination
        if interests:
            query = f"{destination} {interests}"

        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        data = self._extract_json(response.text)
        return DestinationSearchResult(
            destination=destination,
            query=query,
            places=data.get("places", []),
            summary=data.get("summary", ""),
        )
