from datetime import date, datetime
from typing import Optional

# Alias to avoid shadowing `date` type when used as a field name in models
_Date = date

from pydantic import BaseModel, Field, model_validator


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


class PlaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = None
    address: Optional[str] = None
    estimated_cost: Optional[float] = Field(default=None, ge=0)
    ai_reason: Optional[str] = None
    order: Optional[int] = Field(default=None, ge=0)


class PlaceReorderRequest(BaseModel):
    place_ids: list[int] = Field(..., min_length=1)


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


class DayItineraryUpdate(BaseModel):
    date: Optional[_Date] = None
    notes: Optional[str] = None
    transport: Optional[str] = None


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
    date: Optional[_Date] = None
    notes: str = ""


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    amount: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = None
    date: Optional[_Date] = None
    notes: Optional[str] = None


class ExpenseOut(ExpenseBase):
    id: int
    travel_plan_id: int

    model_config = {"from_attributes": True}


class BudgetSummary(BaseModel):
    plan_id: int
    budget: float
    total_spent: float
    remaining: float
    by_category: dict[str, float]
    expense_count: int


# --- TravelPlan ---

class TravelPlanBase(BaseModel):
    destination: str = Field(..., min_length=1, max_length=255)
    start_date: date
    end_date: date
    budget: float = Field(..., gt=0)
    interests: str = ""
    status: str = Field(default="draft", pattern="^(draft|confirmed)$")
    notes: str = ""

    @model_validator(mode="after")
    def end_date_not_before_start_date(self) -> "TravelPlanBase":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class TravelPlanCreate(TravelPlanBase):
    pass


class TravelPlanUpdate(BaseModel):
    destination: Optional[str] = Field(default=None, min_length=1, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = Field(default=None, gt=0)
    interests: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|confirmed)$")
    notes: Optional[str] = None

    @model_validator(mode="after")
    def end_date_not_before_start_date(self) -> "TravelPlanUpdate":
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("end_date must not be before start_date")
        return self


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


class PaginatedPlans(BaseModel):
    items: list[TravelPlanSummary]
    total: int
    page: int
    page_size: int
    pages: int
