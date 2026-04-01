from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai import GeminiService
from app.database import get_db
from app.models import DayItinerary, Place, TravelPlan
from app.schemas import TravelPlanCreate, TravelPlanOut

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/generate", response_model=TravelPlanOut, status_code=201)
def generate_travel_plan(payload: TravelPlanCreate, db: Session = Depends(get_db)):
    """Generate a travel plan using Gemini AI and persist it to the database."""
    service = GeminiService()

    try:
        result = service.generate_itinerary(
            destination=payload.destination,
            start_date=payload.start_date,
            end_date=payload.end_date,
            budget=payload.budget,
            interests=payload.interests,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}")

    plan = TravelPlan(
        destination=payload.destination,
        start_date=payload.start_date,
        end_date=payload.end_date,
        budget=payload.budget,
        interests=payload.interests,
        status=payload.status,
    )
    db.add(plan)
    db.flush()

    for ai_day in result.days:
        try:
            day_date = date.fromisoformat(ai_day.date)
        except ValueError:
            continue

        itinerary = DayItinerary(
            travel_plan_id=plan.id,
            date=day_date,
            notes=ai_day.notes,
            transport=ai_day.transport,
        )
        db.add(itinerary)
        db.flush()

        for order, ai_place in enumerate(ai_day.places):
            db.add(Place(
                day_itinerary_id=itinerary.id,
                name=ai_place.name,
                category=ai_place.category,
                address=ai_place.address,
                estimated_cost=ai_place.estimated_cost,
                ai_reason=ai_place.ai_reason,
                order=order,
            ))

    db.commit()
    db.refresh(plan)
    return plan
