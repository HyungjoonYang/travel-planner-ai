import json
import math
import secrets
from datetime import date as _Date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.ai import GeminiService
from app.database import get_db
from app.models import DayItinerary, Expense, Place, PlanComment, PlanSnapshot, TravelPlan
from app.schemas import (
    CommentCreate, CommentOut,
    PaginatedPlans, PlanSnapshotOut, PlanSnapshotSummary,
    RefineRequest, ShareOut, SnapshotCreateRequest,
    TravelPlanCreate, TravelPlanOut, TravelPlanSummary, TravelPlanUpdate,
)

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
    tag: Optional[str] = Query(default=None, description="Filter by exact tag (case-insensitive)"),
    over_budget: Optional[bool] = Query(default=None, description="Filter plans where total expenses exceed budget"),
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
    if tag is not None:
        t = tag.lower()
        q = q.filter(or_(
            TravelPlan.tags.ilike(t),
            TravelPlan.tags.ilike(f"{t},%"),
            TravelPlan.tags.ilike(f"%,{t}"),
            TravelPlan.tags.ilike(f"%,{t},%"),
        ))
    if over_budget is not None:
        expense_totals = (
            db.query(Expense.travel_plan_id, func.sum(Expense.amount).label("total"))
            .group_by(Expense.travel_plan_id)
            .subquery()
        )
        if over_budget:
            q = q.outerjoin(expense_totals, TravelPlan.id == expense_totals.c.travel_plan_id).filter(
                func.coalesce(expense_totals.c.total, 0) > TravelPlan.budget
            )
        else:
            q = q.outerjoin(expense_totals, TravelPlan.id == expense_totals.c.travel_plan_id).filter(
                func.coalesce(expense_totals.c.total, 0) <= TravelPlan.budget
            )
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
        tags=original.tags,
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


@router.post("/{plan_id}/refine", response_model=TravelPlanOut)
def refine_travel_plan(plan_id: int, payload: RefineRequest, db: Session = Depends(get_db)):
    """Refine an existing travel plan's itinerary using AI based on a natural language instruction."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    current_days = []
    for day in sorted(plan.itineraries, key=lambda d: d.date):
        current_days.append({
            "date": str(day.date),
            "notes": day.notes,
            "transport": day.transport,
            "places": [
                {
                    "name": p.name,
                    "category": p.category,
                    "address": p.address,
                    "estimated_cost": p.estimated_cost,
                    "ai_reason": p.ai_reason,
                }
                for p in sorted(day.places, key=lambda p: p.order)
            ],
        })

    service = GeminiService()
    try:
        result = service.refine_itinerary(
            destination=plan.destination,
            start_date=plan.start_date,
            end_date=plan.end_date,
            budget=plan.budget,
            interests=plan.interests,
            current_days=current_days,
            instruction=payload.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI refinement failed: {exc}")

    # Replace existing itineraries (cascades to places via model cascade)
    for day in list(plan.itineraries):
        db.delete(day)
    db.flush()

    from datetime import date as _date
    for ai_day in result.days:
        try:
            day_date = _date.fromisoformat(ai_day.date)
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


@router.post("/{plan_id}/share", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def share_travel_plan(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """Generate a shareable read-only token for a travel plan."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    if not plan.is_shared or not plan.share_token:
        plan.share_token = secrets.token_urlsafe(32)
        plan.is_shared = True
        db.commit()
        db.refresh(plan)

    base_url = str(request.base_url).rstrip("/")
    share_url = f"{base_url}/travel-plans/shared/{plan.share_token}"
    return ShareOut(plan_id=plan.id, token=plan.share_token, share_url=share_url)


@router.delete("/{plan_id}/share", status_code=status.HTTP_204_NO_CONTENT)
def unshare_travel_plan(plan_id: int, db: Session = Depends(get_db)):
    """Revoke the shareable link for a travel plan."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    plan.is_shared = False
    plan.share_token = None
    db.commit()


@router.get("/shared/{token}", response_model=TravelPlanOut)
def get_shared_travel_plan(token: str, db: Session = Depends(get_db)):
    """Public read-only access to a shared travel plan via token."""
    plan = db.query(TravelPlan).filter(
        TravelPlan.share_token == token,
        TravelPlan.is_shared == True,  # noqa: E712
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Shared plan not found")
    return plan


# --- Comment endpoints ---

def _get_shared_plan_or_404(token: str, db: Session) -> TravelPlan:
    plan = db.query(TravelPlan).filter(
        TravelPlan.share_token == token,
        TravelPlan.is_shared == True,  # noqa: E712
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Shared plan not found")
    return plan


@router.post("/shared/{token}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def create_comment(token: str, payload: CommentCreate, db: Session = Depends(get_db)):
    """Add an anonymous comment to a shared travel plan."""
    plan = _get_shared_plan_or_404(token, db)
    comment = PlanComment(
        travel_plan_id=plan.id,
        author_name=payload.author_name,
        text=payload.text,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/shared/{token}/comments", response_model=list[CommentOut])
def list_comments(token: str, db: Session = Depends(get_db)):
    """List all comments for a shared travel plan, oldest first."""
    plan = _get_shared_plan_or_404(token, db)
    return (
        db.query(PlanComment)
        .filter(PlanComment.travel_plan_id == plan.id)
        .order_by(PlanComment.created_at.asc())
        .all()
    )


@router.delete("/{plan_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(plan_id: int, comment_id: int, db: Session = Depends(get_db)):
    """Owner deletes a comment by its ID (plan must exist)."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")
    comment = db.query(PlanComment).filter(
        PlanComment.id == comment_id,
        PlanComment.travel_plan_id == plan_id,
    ).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    db.delete(comment)
    db.commit()


# --- Snapshot endpoints ---

@router.post("/{plan_id}/snapshot", response_model=PlanSnapshotOut, status_code=status.HTTP_201_CREATED)
def create_snapshot(plan_id: int, payload: SnapshotCreateRequest, db: Session = Depends(get_db)):
    """Create a version snapshot of the current plan state."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    plan_data = TravelPlanOut.model_validate(plan).model_dump(mode="json")
    snap = PlanSnapshot(
        travel_plan_id=plan_id,
        label=payload.label,
        snapshot_data=json.dumps(plan_data),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return PlanSnapshotOut(
        id=snap.id,
        travel_plan_id=snap.travel_plan_id,
        label=snap.label,
        created_at=snap.created_at,
        snapshot_data=plan_data,
    )


@router.get("/{plan_id}/snapshots", response_model=list[PlanSnapshotSummary])
def list_snapshots(plan_id: int, db: Session = Depends(get_db)):
    """List all version snapshots for a travel plan (lightweight, no snapshot_data)."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    return (
        db.query(PlanSnapshot)
        .filter(PlanSnapshot.travel_plan_id == plan_id)
        .order_by(PlanSnapshot.created_at.desc())
        .all()
    )


@router.get("/{plan_id}/snapshots/{snap_id}", response_model=PlanSnapshotOut)
def get_snapshot(plan_id: int, snap_id: int, db: Session = Depends(get_db)):
    """Retrieve a specific version snapshot (full plan data)."""
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")

    snap = db.query(PlanSnapshot).filter(
        PlanSnapshot.id == snap_id,
        PlanSnapshot.travel_plan_id == plan_id,
    ).first()
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return PlanSnapshotOut(
        id=snap.id,
        travel_plan_id=snap.travel_plan_id,
        label=snap.label,
        created_at=snap.created_at,
        snapshot_data=json.loads(snap.snapshot_data),
    )
