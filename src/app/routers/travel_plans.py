from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TravelPlan
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
