from datetime import date, datetime
from typing import Optional

# Alias to avoid shadowing `date` type when used as a field name in models
_Date = date

from pydantic import BaseModel, Field, model_validator  # noqa: E402


# --- Place ---

class PlaceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: str = ""
    address: str = ""
    estimated_cost: float = Field(default=0.0, ge=0)
    ai_reason: str = ""
    order: int = Field(default=0, ge=0)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    review: Optional[str] = None


class PlaceCreate(PlaceBase):
    pass


class PlaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = None
    address: Optional[str] = None
    estimated_cost: Optional[float] = Field(default=None, ge=0)
    ai_reason: Optional[str] = None
    order: Optional[int] = Field(default=None, ge=0)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    review: Optional[str] = None


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
    over_budget: bool
    overage_pct: float


# --- TravelPlan ---

class TravelPlanBase(BaseModel):
    destination: str = Field(..., min_length=1, max_length=255)
    start_date: date
    end_date: date
    budget: float = Field(..., gt=0)
    interests: str = ""
    status: str = Field(default="draft", pattern="^(draft|confirmed)$")
    notes: str = ""
    tags: str = ""

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
    tags: Optional[str] = None

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
    is_shared: bool = False
    itineraries: list[DayItineraryOut] = []
    expenses: list[ExpenseOut] = []

    model_config = {"from_attributes": True}


class TravelPlanSummary(TravelPlanBase):
    """Lightweight response without nested relations."""
    id: int
    created_at: datetime
    updated_at: datetime
    is_shared: bool = False

    model_config = {"from_attributes": True}


class PaginatedPlans(BaseModel):
    items: list[TravelPlanSummary]
    total: int
    page: int
    page_size: int
    pages: int


class ShareOut(BaseModel):
    plan_id: int
    token: str
    share_url: str


class RefineRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=2000, description="Natural language instruction for how to refine the travel plan")


# --- PlanSnapshot ---

class SnapshotCreateRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=100, description="Optional short description for the snapshot")


class PlanSnapshotSummary(BaseModel):
    id: int
    travel_plan_id: int
    label: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanSnapshotOut(BaseModel):
    id: int
    travel_plan_id: int
    label: Optional[str]
    created_at: datetime
    snapshot_data: dict

    model_config = {"from_attributes": True}


# --- PlanComment ---

# --- TopPlace ---

class TopPlaceOut(BaseModel):
    id: int
    name: str
    category: str
    address: str
    estimated_cost: float
    ai_reason: str
    order: int
    rating: int
    review: Optional[str]
    day_itinerary_id: int
    day_date: date

    model_config = {"from_attributes": True}


class CommentCreate(BaseModel):
    author_name: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=1, max_length=2000)


class CommentOut(BaseModel):
    id: int
    travel_plan_id: int
    author_name: str
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Chat ---

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChatSessionOut(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime


class AgentStatusEvent(BaseModel):
    agent: str
    status: str  # idle | thinking | working | done | error
    message: str
    result_count: Optional[int] = None


# --- DayStats ---

class DayStats(BaseModel):
    day_id: int
    place_count: int
    total_estimated_cost: float
    by_category: dict[str, float]
