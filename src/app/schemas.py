from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# --- Place ---

class PlaceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: str = ""
    address: str = ""
    estimated_cost: float = Field(default=0.0, ge=0)
    ai_reason: str = ""
    order: int = Field(default=0, ge=0)


class PlaceCreate(PlaceBase):
    pass


class PlaceOut(PlaceBase):
    id: int
    day_itinerary_id: int

    model_config = {"from_attributes": True}


# --- DayItinerary ---

class DayItineraryBase(BaseModel):
    date: date
    notes: str = ""
    transport: str = ""


class DayItineraryCreate(DayItineraryBase):
    places: list[PlaceCreate] = []


class DayItineraryOut(DayItineraryBase):
    id: int
    travel_plan_id: int
    places: list[PlaceOut] = []

    model_config = {"from_attributes": True}


# --- Expense ---

class ExpenseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category: str = ""
    date: Optional[date] = None
    notes: str = ""


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseOut(ExpenseBase):
    id: int
    travel_plan_id: int

    model_config = {"from_attributes": True}


# --- TravelPlan ---

class TravelPlanBase(BaseModel):
    destination: str = Field(..., min_length=1, max_length=255)
    start_date: date
    end_date: date
    budget: float = Field(..., gt=0)
    interests: str = ""
    status: str = Field(default="draft", pattern="^(draft|confirmed)$")


class TravelPlanCreate(TravelPlanBase):
    pass


class TravelPlanUpdate(BaseModel):
    destination: Optional[str] = Field(default=None, min_length=1, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = Field(default=None, gt=0)
    interests: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|confirmed)$")


class TravelPlanOut(TravelPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime
    itineraries: list[DayItineraryOut] = []
    expenses: list[ExpenseOut] = []

    model_config = {"from_attributes": True}


class TravelPlanSummary(TravelPlanBase):
    """Lightweight response without nested relations."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
