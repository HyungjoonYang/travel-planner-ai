"""Manual itinerary editing — CRUD for DayItinerary and Place (Task #21)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DayItinerary, Place, TravelPlan
from app.schemas import (
    DayItineraryCreate,
    DayItineraryOut,
    DayItineraryUpdate,
    PlaceCreate,
    PlaceOut,
    PlaceReorderRequest,
    PlaceUpdate,
)

router = APIRouter(prefix="/plans/{plan_id}/itineraries", tags=["itineraries"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_plan_or_404(plan_id: int, db: Session) -> TravelPlan:
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")
    return plan


def _get_day_or_404(plan_id: int, day_id: int, db: Session) -> DayItinerary:
    day = db.get(DayItinerary, day_id)
    if day is None or day.travel_plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Day itinerary not found")
    return day


def _get_place_or_404(day_id: int, place_id: int, db: Session) -> Place:
    place = db.get(Place, place_id)
    if place is None or place.day_itinerary_id != day_id:
        raise HTTPException(status_code=404, detail="Place not found")
    return place


# ---------------------------------------------------------------------------
# DayItinerary endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=DayItineraryOut, status_code=status.HTTP_201_CREATED)
def add_day(plan_id: int, payload: DayItineraryCreate, db: Session = Depends(get_db)):
    _get_plan_or_404(plan_id, db)
    day = DayItinerary(
        travel_plan_id=plan_id,
        date=payload.date,
        notes=payload.notes,
        transport=payload.transport,
    )
    db.add(day)
    db.flush()  # get day.id before adding places
    for p in payload.places:
        db.add(Place(day_itinerary_id=day.id, **p.model_dump()))
    db.commit()
    db.refresh(day)
    return day


@router.get("", response_model=list[DayItineraryOut])
def list_days(plan_id: int, db: Session = Depends(get_db)):
    _get_plan_or_404(plan_id, db)
    return (
        db.query(DayItinerary)
        .filter(DayItinerary.travel_plan_id == plan_id)
        .order_by(DayItinerary.date)
        .all()
    )


@router.get("/{day_id}", response_model=DayItineraryOut)
def get_day(plan_id: int, day_id: int, db: Session = Depends(get_db)):
    return _get_day_or_404(plan_id, day_id, db)


@router.patch("/{day_id}", response_model=DayItineraryOut)
def update_day(
    plan_id: int, day_id: int, payload: DayItineraryUpdate, db: Session = Depends(get_db)
):
    day = _get_day_or_404(plan_id, day_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(day, field, value)
    db.commit()
    db.refresh(day)
    return day


@router.delete("/{day_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_day(plan_id: int, day_id: int, db: Session = Depends(get_db)):
    day = _get_day_or_404(plan_id, day_id, db)
    db.delete(day)
    db.commit()


# ---------------------------------------------------------------------------
# Place endpoints (nested under a day)
# ---------------------------------------------------------------------------

@router.post("/{day_id}/places", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
def add_place(
    plan_id: int, day_id: int, payload: PlaceCreate, db: Session = Depends(get_db)
):
    _get_day_or_404(plan_id, day_id, db)
    place = Place(day_itinerary_id=day_id, **payload.model_dump())
    db.add(place)
    db.commit()
    db.refresh(place)
    return place


@router.patch("/{day_id}/places/reorder", response_model=list[PlaceOut])
def reorder_places(
    plan_id: int,
    day_id: int,
    payload: PlaceReorderRequest,
    db: Session = Depends(get_db),
):
    """Atomically reorder places within a day by supplying an ordered list of place IDs.

    All place IDs that belong to the day must be provided (no extras, no omissions).
    Each place's ``order`` field is set to its index (0-based) in the supplied list.
    """
    _get_day_or_404(plan_id, day_id, db)
    day_places: list[Place] = (
        db.query(Place).filter(Place.day_itinerary_id == day_id).all()
    )
    existing_ids = {p.id for p in day_places}
    requested_ids = payload.place_ids

    if set(requested_ids) != existing_ids:
        raise HTTPException(
            status_code=422,
            detail="place_ids must contain exactly the places belonging to this day",
        )
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(
            status_code=422,
            detail="place_ids must not contain duplicates",
        )

    place_map = {p.id: p for p in day_places}
    for new_order, place_id in enumerate(requested_ids):
        place_map[place_id].order = new_order
    db.commit()
    for p in day_places:
        db.refresh(p)
    return sorted(day_places, key=lambda p: p.order)


@router.patch("/{day_id}/places/{place_id}", response_model=PlaceOut)
def update_place(
    plan_id: int,
    day_id: int,
    place_id: int,
    payload: PlaceUpdate,
    db: Session = Depends(get_db),
):
    _get_day_or_404(plan_id, day_id, db)
    place = _get_place_or_404(day_id, place_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(place, field, value)
    db.commit()
    db.refresh(place)
    return place


@router.delete("/{day_id}/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_place(
    plan_id: int, day_id: int, place_id: int, db: Session = Depends(get_db)
):
    _get_day_or_404(plan_id, day_id, db)
    place = _get_place_or_404(day_id, place_id, db)
    db.delete(place)
    db.commit()
