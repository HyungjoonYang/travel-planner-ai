"""Google Calendar integration service.

Uses the Google Calendar REST API via httpx (no heavy Google SDK dependency).
Access tokens are provided per-request (OAuth 2.0 Bearer tokens).
"""
from datetime import date, timedelta

import httpx
from pydantic import BaseModel

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


class CalendarEventResult(BaseModel):
    day_itinerary_id: int
    event_date: date
    event_id: str
    event_link: str


class CalendarExportResult(BaseModel):
    plan_id: int
    destination: str
    events_created: int
    events: list[CalendarEventResult]


class CalendarService:
    """Wraps the Google Calendar REST API for travel plan export."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _build_event_body(self, itinerary, destination: str) -> dict:
        """Build a Google Calendar event payload for a single day itinerary."""
        place_lines = []
        for place in sorted(itinerary.places, key=lambda p: p.order):
            line = f"- {place.name}"
            if place.category:
                line += f" ({place.category})"
            if place.ai_reason:
                line += f": {place.ai_reason}"
            place_lines.append(line)

        description_parts = []
        if itinerary.transport:
            description_parts.append(f"Transport: {itinerary.transport}")
        if place_lines:
            description_parts.append("Places:\n" + "\n".join(place_lines))
        if itinerary.notes:
            description_parts.append(f"Notes: {itinerary.notes}")

        description = "\n\n".join(description_parts)

        # All-day events: end date is exclusive (start + 1 day)
        end_date = itinerary.date + timedelta(days=1)

        return {
            "summary": f"{destination} — {itinerary.date.strftime('%b %d')}",
            "description": description,
            "start": {"date": itinerary.date.isoformat()},
            "end": {"date": end_date.isoformat()},
            "location": destination,
        }

    def create_event(self, event_body: dict) -> dict:
        """POST a single event to Google Calendar and return the API response."""
        with httpx.Client() as client:
            response = client.post(
                f"{CALENDAR_API_BASE}/calendars/primary/events",
                headers=self._headers,
                json=event_body,
            )
            response.raise_for_status()
            return response.json()

    def export_plan(self, plan) -> CalendarExportResult:
        """Export all day itineraries of a travel plan to Google Calendar."""
        events: list[CalendarEventResult] = []

        for itinerary in sorted(plan.itineraries, key=lambda x: x.date):
            body = self._build_event_body(itinerary, plan.destination)
            api_response = self.create_event(body)
            events.append(
                CalendarEventResult(
                    day_itinerary_id=itinerary.id,
                    event_date=itinerary.date,
                    event_id=api_response["id"],
                    event_link=api_response.get("htmlLink", ""),
                )
            )

        return CalendarExportResult(
            plan_id=plan.id,
            destination=plan.destination,
            events_created=len(events),
            events=events,
        )
