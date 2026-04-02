import json
import math
from datetime import date as _Date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DayItinerary, Place, TravelPlan
from app.schemas import PaginatedPlans, TravelPlanCreate, TravelPlanOut, TravelPlanSummary, TravelPlanUpdate

router = APIRouter(prefix="/travel-plans", tags=["travel-plans"])


@router.post("", response_model=TravelPlanOut, status_code=status.HTTP_201_CREATED)
def create_travel_plan(payload: TravelPlanCreate, db: Session = Depends(get_db)):
    plan = TravelPlan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("", response_model=PaginatedPlans)
def list_travel_plans(
    destination: Optional[str] = Query(default=None, description="Case-insensitive partial match on destination"),
    status_filter: Optional[str] = Query(default=None, alias="status", pattern="^(draft|confirmed)$"),
    from_date: Optional[_Date] = Query(default=None, alias="from", description="Filter plans where start_date >= this date"),
    to_date: Optional[_Date] = Query(default=None, alias="to", description="Filter plans where start_date <= this date"),
    notes: Optional[str] = Query(default=None, description="Case-insensitive keyword search in notes"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page (max 100)"),
    db: Session = Depends(get_db),
):
    q = db.query(TravelPlan)
    if destination is not None:
        q = q.filter(TravelPlan.destination.ilike(f"%{destination}%"))
    if status_filter is not None:
        q = q.filter(TravelPlan.status == status_filter)
    if from_date is not None:
        q = q.filter(TravelPlan.start_date >= from_date)
    if to_date is not None:
        q = q.filter(TravelPlan.start_date <= to_date)
    if notes is not None:
        q = q.filter(TravelPlan.notes.ilike(f"%{notes}%"))
    q = q.order_by(TravelPlan.created_at.desc(), TravelPlan.id.desc())
    total = q.count()
    pages = max(1, math.ceil(total / page_size))
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedPlans(items=items, total=total, page=page, page_size=page_size, pages=pages)


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
        notes=original.notes,
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


@router.get("/{plan_id}/export")
def export_travel_plan(plan_id: int, db: Session = Depends(get_db)):
    """Return full plan JSON (plan + itineraries + places + expenses) as a downloadable file."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    plan_data = TravelPlanOut.model_validate(plan).model_dump(mode="json")
    filename = f"travel-plan-{plan_id}.json"
    content = json.dumps(plan_data, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
