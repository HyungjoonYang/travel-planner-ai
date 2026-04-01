"""Tests for SQLAlchemy models and Pydantic schemas."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401 — register models
from app.models import TravelPlan, DayItinerary, Place, Expense
from app.schemas import (
    TravelPlanCreate,
    TravelPlanUpdate,
    TravelPlanOut,
    TravelPlanSummary,
    DayItineraryCreate,
    ExpenseCreate,
    PlaceCreate,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# --- ORM model tests ---

class TestTravelPlanModel:
    def test_create_travel_plan(self, db_session):
        plan = TravelPlan(
            destination="Tokyo, Japan",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
            budget=2000.0,
            interests="food,culture",
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()
        db_session.refresh(plan)

        assert plan.id is not None
        assert plan.destination == "Tokyo, Japan"
        assert plan.status == "draft"
        assert plan.budget == 2000.0

    def test_travel_plan_defaults(self, db_session):
        plan = TravelPlan(
            destination="Paris",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            budget=1500.0,
        )
        db_session.add(plan)
        db_session.commit()
        db_session.refresh(plan)

        assert plan.status == "draft"
        assert plan.interests == ""

    def test_travel_plan_cascade_delete(self, db_session):
        plan = TravelPlan(
            destination="Seoul",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 3),
            budget=1000.0,
        )
        db_session.add(plan)
        db_session.commit()

        itinerary = DayItinerary(
            travel_plan_id=plan.id,
            date=date(2026, 7, 1),
        )
        db_session.add(itinerary)
        expense = Expense(
            travel_plan_id=plan.id,
            name="Flight",
            amount=500.0,
            category="transport",
        )
        db_session.add(expense)
        db_session.commit()

        db_session.delete(plan)
        db_session.commit()

        assert db_session.query(DayItinerary).count() == 0
        assert db_session.query(Expense).count() == 0


class TestDayItineraryModel:
    def test_create_day_itinerary_with_places(self, db_session):
        plan = TravelPlan(
            destination="Osaka",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            budget=800.0,
        )
        db_session.add(plan)
        db_session.commit()

        itinerary = DayItinerary(
            travel_plan_id=plan.id,
            date=date(2026, 8, 1),
            notes="First day",
            transport="subway",
        )
        db_session.add(itinerary)
        db_session.commit()

        place = Place(
            day_itinerary_id=itinerary.id,
            name="Dotonbori",
            category="sightseeing",
            address="Dotonbori, Chuo Ward, Osaka",
            estimated_cost=0.0,
            ai_reason="Famous entertainment district",
            order=1,
        )
        db_session.add(place)
        db_session.commit()
        db_session.refresh(itinerary)

        assert len(itinerary.places) == 1
        assert itinerary.places[0].name == "Dotonbori"


class TestExpenseModel:
    def test_create_expense(self, db_session):
        plan = TravelPlan(
            destination="Berlin",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            budget=1200.0,
        )
        db_session.add(plan)
        db_session.commit()

        expense = Expense(
            travel_plan_id=plan.id,
            name="Hotel stay",
            amount=300.0,
            category="lodging",
            date=date(2026, 9, 1),
        )
        db_session.add(expense)
        db_session.commit()
        db_session.refresh(expense)

        assert expense.id is not None
        assert expense.amount == 300.0
        assert expense.category == "lodging"


# --- Pydantic schema tests ---

class TestTravelPlanSchemas:
    def test_create_schema_valid(self):
        data = TravelPlanCreate(
            destination="Tokyo",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
            budget=2000.0,
            interests="food,culture",
        )
        assert data.status == "draft"
        assert data.destination == "Tokyo"

    def test_create_schema_invalid_status(self):
        with pytest.raises(Exception):
            TravelPlanCreate(
                destination="Tokyo",
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 7),
                budget=2000.0,
                status="invalid_status",
            )

    def test_create_schema_invalid_budget(self):
        with pytest.raises(Exception):
            TravelPlanCreate(
                destination="Tokyo",
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 7),
                budget=-100.0,
            )

    def test_update_schema_partial(self):
        update = TravelPlanUpdate(destination="Kyoto")
        assert update.destination == "Kyoto"
        assert update.budget is None
        assert update.status is None

    def test_out_schema_from_orm(self, db_session):
        plan = TravelPlan(
            destination="Rome",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 7),
            budget=1800.0,
        )
        db_session.add(plan)
        db_session.commit()
        db_session.refresh(plan)

        out = TravelPlanSummary.model_validate(plan)
        assert out.id == plan.id
        assert out.destination == "Rome"


class TestExpenseSchema:
    def test_expense_create_valid(self):
        exp = ExpenseCreate(name="Dinner", amount=50.0, category="food")
        assert exp.amount == 50.0

    def test_expense_create_invalid_amount(self):
        with pytest.raises(Exception):
            ExpenseCreate(name="Dinner", amount=0.0)


class TestPlaceSchema:
    def test_place_create_valid(self):
        p = PlaceCreate(name="Eiffel Tower", category="sightseeing", estimated_cost=25.0)
        assert p.name == "Eiffel Tower"

    def test_place_invalid_empty_name(self):
        with pytest.raises(Exception):
            PlaceCreate(name="")
