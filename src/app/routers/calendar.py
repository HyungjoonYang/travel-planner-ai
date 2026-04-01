from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx

from app.calendar_service import CalendarExportResult, CalendarService
from app.database import get_db
from app.models import TravelPlan

router = APIRouter(prefix="/plans", tags=["calendar"])


class CalendarExportRequest(BaseModel):
    access_token: str


@router.post("/{plan_id}/calendar/export", response_model=CalendarExportResult)
def export_plan_to_calendar(
    plan_id: int,
    body: CalendarExportRequest,
    db: Session = Depends(get_db),
):
    """Export a travel plan's itinerary to Google Calendar as all-day events.

    Requires a valid Google OAuth 2.0 access token with the
    https://www.googleapis.com/auth/calendar.events scope.
    """
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    if not plan.itineraries:
        raise HTTPException(
            status_code=422,
            detail="Travel plan has no itinerary days to export",
        )

    service = CalendarService(access_token=body.access_token)
    try:
        result = service.export_plan(plan)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            raise HTTPException(
                status_code=401, detail="Invalid or expired Google access token"
            )
        raise HTTPException(
            status_code=502,
            detail=f"Google Calendar API error: {status}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Google Calendar API: {exc}",
        )

    return result
