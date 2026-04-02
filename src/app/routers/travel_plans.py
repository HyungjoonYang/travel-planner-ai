from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DayItinerary, Place, TravelPlan
from app.schemas import TravelPlanCreate, TravelPlanOut, TravelPlanSummary, TravelPlanUpdate

router = APIRouter(prefix="/travel-plans", tags=["travel-plans"])


@router.post("", response_model=TravelPlanOut, status_code=status.HTTP_201_CREATED)
def create_travel_plan(payload: TravelPlanCreate, db: Session = Depends(get_db)):
    plan = TravelPlan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("", response_model=list[TravelPlanSummary])
def list_travel_plans(db: Session = Depends(get_db)):
    return db.query(TravelPlan).order_by(TravelPlan.created_at.desc()).all()


@router.get("/{plan_id}", response_model=TravelPlanOut)
def get_travel_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")
    return plan


@router.patch("/{plan_id}", response_model=TravelPlanOut)
def update_travel_plan(
    plan_id: int, payload: TravelPlanUpdate, db: Session = Depends(get_db)
):
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_travel_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")
    db.delete(plan)
    db.commit()


@router.post("/{plan_id}/duplicate", response_model=TravelPlanOut, status_code=status.HTTP_201_CREATED)
def duplicate_travel_plan(plan_id: int, db: Session = Depends(get_db)):
    """Copy a travel plan (with its itineraries and places) as a new draft."""
    original = db.get(TravelPlan, plan_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    copy = TravelPlan(
        destination=original.destination,
        start_date=original.start_date,
        end_date=original.end_date,
        budget=original.budget,
        interests=original.interests,
        status="draft",
    )
    db.add(copy)
    db.flush()  # assign copy.id before creating children

    for day in original.itineraries:
        day_copy = DayItinerary(
            travel_plan_id=copy.id,
            date=day.date,
            notes=day.notes,
            transport=day.transport,
        )
        db.add(day_copy)
        db.flush()

        for place in day.places:
            db.add(Place(
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
    return copy
