"""Unit tests for Pydantic schemas — no DB, no HTTP client required."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from datetime import date
from pydantic import ValidationError

from app.schemas import (
    TravelPlanCreate,
    TravelPlanUpdate,
    PlaceCreate,
    DayItineraryCreate,
    ExpenseCreate,
)

VALID_PLAN = dict(
    destination="Tokyo",
    start_date=date(2026, 7, 1),
    end_date=date(2026, 7, 10),
    budget=3000.0,
)


class TestTravelPlanCreate:
    def test_valid_minimal(self):
        plan = TravelPlanCreate(**VALID_PLAN)
        assert plan.destination == "Tokyo"
        assert plan.status == "draft"
        assert plan.interests == ""

    def test_valid_full(self):
        plan = TravelPlanCreate(
            **VALID_PLAN,
            interests="food,culture,nature",
            status="confirmed",
        )
        assert plan.status == "confirmed"
        assert plan.interests == "food,culture,nature"

    def test_destination_required(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
                budget=1000.0,
            )

    def test_destination_empty_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "destination": ""})

    def test_destination_max_length_ok(self):
        plan = TravelPlanCreate(**{**VALID_PLAN, "destination": "A" * 255})
        assert len(plan.destination) == 255

    def test_destination_over_max_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "destination": "A" * 256})

    def test_start_date_required(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(
                destination="Tokyo",
                end_date=date(2026, 7, 10),
                budget=1000.0,
            )

    def test_end_date_required(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(
                destination="Tokyo",
                start_date=date(2026, 7, 1),
                budget=1000.0,
            )

    def test_budget_required(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(
                destination="Tokyo",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
            )

    def test_budget_zero_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "budget": 0})

    def test_budget_negative_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "budget": -100})

    def test_budget_small_positive_ok(self):
        plan = TravelPlanCreate(**{**VALID_PLAN, "budget": 0.01})
        assert plan.budget == pytest.approx(0.01)

    def test_status_default_draft(self):
        plan = TravelPlanCreate(**VALID_PLAN)
        assert plan.status == "draft"

    def test_status_confirmed_ok(self):
        plan = TravelPlanCreate(**{**VALID_PLAN, "status": "confirmed"})
        assert plan.status == "confirmed"

    def test_status_invalid_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "status": "pending"})

    def test_status_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "status": "DRAFT"})

    def test_status_mixed_case_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanCreate(**{**VALID_PLAN, "status": "Draft"})


class TestTravelPlanUpdate:
    def test_empty_update_ok(self):
        update = TravelPlanUpdate()
        assert update.destination is None
        assert update.status is None
        assert update.budget is None
        assert update.start_date is None
        assert update.end_date is None
        assert update.interests is None

    def test_partial_destination(self):
        update = TravelPlanUpdate(destination="Seoul")
        assert update.destination == "Seoul"
        assert update.budget is None

    def test_partial_budget(self):
        update = TravelPlanUpdate(budget=5000.0)
        assert update.budget == 5000.0
        assert update.destination is None

    def test_partial_status(self):
        update = TravelPlanUpdate(status="confirmed")
        assert update.status == "confirmed"

    def test_destination_empty_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanUpdate(destination="")

    def test_destination_max_length_ok(self):
        update = TravelPlanUpdate(destination="B" * 255)
        assert len(update.destination) == 255

    def test_destination_over_max_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanUpdate(destination="B" * 256)

    def test_budget_zero_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanUpdate(budget=0)

    def test_budget_negative_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanUpdate(budget=-1)

    def test_status_invalid_rejected(self):
        with pytest.raises(ValidationError):
            TravelPlanUpdate(status="in_progress")

    def test_all_fields_together(self):
        update = TravelPlanUpdate(
            destination="Berlin",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 7),
            budget=2000.0,
            interests="history,art",
            status="confirmed",
        )
        assert update.destination == "Berlin"
        assert update.budget == 2000.0
        assert update.status == "confirmed"


class TestPlaceCreate:
    def test_valid_minimal(self):
        place = PlaceCreate(name="Eiffel Tower")
        assert place.name == "Eiffel Tower"
        assert place.estimated_cost == 0.0
        assert place.order == 0
        assert place.category == ""
        assert place.address == ""
        assert place.ai_reason == ""

    def test_name_required(self):
        with pytest.raises(ValidationError):
            PlaceCreate()

    def test_name_empty_rejected(self):
        with pytest.raises(ValidationError):
            PlaceCreate(name="")

    def test_name_max_length_ok(self):
        place = PlaceCreate(name="C" * 255)
        assert len(place.name) == 255

    def test_name_over_max_rejected(self):
        with pytest.raises(ValidationError):
            PlaceCreate(name="C" * 256)

    def test_estimated_cost_zero_ok(self):
        place = PlaceCreate(name="Park", estimated_cost=0)
        assert place.estimated_cost == 0

    def test_estimated_cost_negative_rejected(self):
        with pytest.raises(ValidationError):
            PlaceCreate(name="Museum", estimated_cost=-1)

    def test_estimated_cost_positive_ok(self):
        place = PlaceCreate(name="Restaurant", estimated_cost=45.5)
        assert place.estimated_cost == pytest.approx(45.5)

    def test_order_default_zero(self):
        place = PlaceCreate(name="Cafe")
        assert place.order == 0

    def test_order_positive_ok(self):
        place = PlaceCreate(name="Gallery", order=3)
        assert place.order == 3

    def test_order_negative_rejected(self):
        with pytest.raises(ValidationError):
            PlaceCreate(name="Gallery", order=-1)

    def test_valid_full(self):
        place = PlaceCreate(
            name="Louvre Museum",
            category="museum",
            address="Rue de Rivoli, Paris",
            estimated_cost=20.0,
            ai_reason="World-class art collection",
            order=1,
        )
        assert place.name == "Louvre Museum"
        assert place.category == "museum"
        assert place.order == 1


class TestExpenseCreate:
    def test_valid_minimal(self):
        expense = ExpenseCreate(name="Lunch", amount=25.0)
        assert expense.name == "Lunch"
        assert expense.amount == 25.0
        assert expense.category == ""
        assert expense.date is None
        assert expense.notes == ""

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ExpenseCreate(amount=25.0)

    def test_amount_required(self):
        with pytest.raises(ValidationError):
            ExpenseCreate(name="Taxi")

    def test_name_empty_rejected(self):
        with pytest.raises(ValidationError):
            ExpenseCreate(name="", amount=10.0)

    def test_name_max_length_ok(self):
        expense = ExpenseCreate(name="D" * 255, amount=5.0)
        assert len(expense.name) == 255

    def test_name_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ExpenseCreate(name="D" * 256, amount=5.0)

    def test_amount_zero_rejected(self):
        with pytest.raises(ValidationError):
            ExpenseCreate(name="Coffee", amount=0)

    def test_amount_negative_rejected(self):
        with pytest.raises(ValidationError):
            ExpenseCreate(name="Coffee", amount=-5)

    def test_amount_small_positive_ok(self):
        expense = ExpenseCreate(name="Tip", amount=0.01)
        assert expense.amount == pytest.approx(0.01)

    def test_date_optional(self):
        expense = ExpenseCreate(name="Hotel", amount=150.0, date=date(2026, 7, 2))
        assert expense.date == date(2026, 7, 2)

    def test_valid_full(self):
        expense = ExpenseCreate(
            name="Shinkansen",
            amount=120.0,
            category="transport",
            date=date(2026, 7, 3),
            notes="Tokyo to Osaka",
        )
        assert expense.amount == 120.0
        assert expense.category == "transport"
        assert expense.notes == "Tokyo to Osaka"


class TestDayItineraryCreate:
    def test_valid_minimal(self):
        itinerary = DayItineraryCreate(date=date(2026, 7, 1))
        assert itinerary.date == date(2026, 7, 1)
        assert itinerary.places == []
        assert itinerary.notes == ""
        assert itinerary.transport == ""

    def test_date_required(self):
        with pytest.raises(ValidationError):
            DayItineraryCreate()

    def test_places_default_empty_list(self):
        itinerary = DayItineraryCreate(date=date(2026, 7, 1))
        assert itinerary.places == []

    def test_with_places(self):
        itinerary = DayItineraryCreate(
            date=date(2026, 7, 1),
            places=[PlaceCreate(name="Senso-ji"), PlaceCreate(name="Akihabara")],
        )
        assert len(itinerary.places) == 2
        assert itinerary.places[0].name == "Senso-ji"
        assert itinerary.places[1].name == "Akihabara"

    def test_place_in_itinerary_validates(self):
        with pytest.raises(ValidationError):
            DayItineraryCreate(
                date=date(2026, 7, 1),
                places=[{"name": ""}],  # empty name rejected
            )

    def test_notes_and_transport(self):
        itinerary = DayItineraryCreate(
            date=date(2026, 7, 2),
            notes="Rainy day plan",
            transport="subway",
        )
        assert itinerary.notes == "Rainy day plan"
        assert itinerary.transport == "subway"
