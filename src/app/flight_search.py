"""Flight search service using Gemini with Google Search grounding."""
import json
import re

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import GEMINI_API_KEY


class FlightResult(BaseModel):
    airline: str
    flight_number: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    duration: str = ""
    stops: str = ""
    price: str = ""
    cabin_class: str = ""
    tips: str = ""


class FlightSearchResult(BaseModel):
    departure_city: str
    arrival_city: str
    departure_date: str = ""
    return_date: str = ""
    passengers: int = 1
    flights: list[FlightResult]
    summary: str = ""


class FlightSearchService:
    MODEL = "gemini-3-flash-preview"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or GEMINI_API_KEY

    def _build_search_prompt(
        self,
        departure_city: str,
        arrival_city: str,
        departure_date: str = "",
        return_date: str = "",
        passengers: int = 1,
        max_price: int = 0,
    ) -> str:
        date_clause = f" on {departure_date}" if departure_date else ""
        return_clause = f" returning {return_date}" if return_date else ""
        passengers_clause = f" for {passengers} passenger(s)" if passengers > 1 else ""
        price_clause = f" under ${max_price}" if max_price > 0 else ""

        return f"""Search the web for flights from {departure_city} to {arrival_city}{date_clause}{return_clause}{passengers_clause}{price_clause}.

Return a JSON object with this exact structure:
{{
  "flights": [
    {{
      "airline": "Airline name",
      "flight_number": "Flight number (e.g. KE123)",
      "departure_time": "Departure time (e.g. 09:00)",
      "arrival_time": "Arrival time (e.g. 14:30)",
      "duration": "Total flight duration (e.g. 5h 30m)",
      "stops": "Number of stops (e.g. Nonstop or 1 stop via Tokyo)",
      "price": "Price per person (e.g. $350)",
      "cabin_class": "Cabin class (e.g. Economy)",
      "tips": "Booking tips or highlights"
    }}
  ],
  "summary": "Brief overview of flight options from {departure_city} to {arrival_city}"
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

    def search_flights(
        self,
        departure_city: str,
        arrival_city: str,
        departure_date: str = "",
        return_date: str = "",
        passengers: int = 1,
        max_price: int = 0,
    ) -> FlightSearchResult:
        """Search for flights using Gemini with Google Search grounding."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        client = genai.Client(api_key=self._api_key)
        prompt = self._build_search_prompt(
            departure_city, arrival_city, departure_date, return_date, passengers, max_price
        )

        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        data = self._extract_json(response.text)
        return FlightSearchResult(
            departure_city=departure_city,
            arrival_city=arrival_city,
            departure_date=departure_date,
            return_date=return_date,
            passengers=passengers,
            flights=data.get("flights", []),
            summary=data.get("summary", ""),
        )
