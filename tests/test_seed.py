"""Tests for the seed_database function."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DayItinerary, Expense, Place, TravelPlan
from app.seed import SEED_PLANS, seed_database


@pytest.fixture
def db_session():
    """In-memory SQLite session for seed tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestSeedDatabase:
    def test_returns_count_of_inserted_plans(self, db_session):
        inserted = seed_database(db_session)
        assert inserted == len(SEED_PLANS)

    def test_travel_plans_created(self, db_session):
        seed_database(db_session)
        plans = db_session.query(TravelPlan).all()
        assert len(plans) == len(SEED_PLANS)

    def test_first_plan_destination(self, db_session):
        seed_database(db_session)
        plan = db_session.query(TravelPlan).filter_by(destination="Tokyo, Japan").first()
        assert plan is not None

    def test_second_plan_destination(self, db_session):
        seed_database(db_session)
        plan = db_session.query(TravelPlan).filter_by(destination="Paris, France").first()
        assert plan is not None

    def test_plans_have_correct_status(self, db_session):
        seed_database(db_session)
        tokyo = db_session.query(TravelPlan).filter_by(destination="Tokyo, Japan").first()
        paris = db_session.query(TravelPlan).filter_by(destination="Paris, France").first()
        assert tokyo.status == "confirmed"
        assert paris.status == "draft"

    def test_itineraries_created(self, db_session):
        seed_database(db_session)
        count = db_session.query(DayItinerary).count()
        # 2 days for Tokyo + 2 days for Paris = 4
        assert count == 4

    def test_tokyo_itineraries_belong_to_tokyo_plan(self, db_session):
        seed_database(db_session)
        tokyo = db_session.query(TravelPlan).filter_by(destination="Tokyo, Japan").first()
        assert len(tokyo.itineraries) == 2

    def test_paris_itineraries_belong_to_paris_plan(self, db_session):
        seed_database(db_session)
        paris = db_session.query(TravelPlan).filter_by(destination="Paris, France").first()
        assert len(paris.itineraries) == 2

    def test_places_created(self, db_session):
        seed_database(db_session)
        # Tokyo day1: 2, day2: 3; Paris day1: 2, day2: 2 = 9 total
        count = db_session.query(Place).count()
        assert count == 9

    def test_places_have_correct_order(self, db_session):
        seed_database(db_session)
        tokyo = db_session.query(TravelPlan).filter_by(destination="Tokyo, Japan").first()
        day1 = sorted(tokyo.itineraries, key=lambda i: i.date)[0]
        orders = [p.order for p in day1.places]
        assert orders == sorted(orders)

    def test_expenses_created(self, db_session):
        seed_database(db_session)
        # Tokyo: 2, Paris: 1 = 3 total
        count = db_session.query(Expense).count()
        assert count == 3

    def test_expenses_linked_to_correct_plan(self, db_session):
        seed_database(db_session)
        tokyo = db_session.query(TravelPlan).filter_by(destination="Tokyo, Japan").first()
        assert len(tokyo.expenses) == 2

    def test_expense_categories(self, db_session):
        seed_database(db_session)
        categories = {e.category for e in db_session.query(Expense).all()}
        assert "transport" in categories
        assert "lodging" in categories

    def test_skip_if_exists_default(self, db_session):
        """Second call with skip_if_exists=True (default) inserts nothing."""
        seed_database(db_session)
        inserted_second = seed_database(db_session)
        assert inserted_second == 0

    def test_skip_if_exists_false_re_seeds(self, db_session):
        """skip_if_exists=False inserts even when rows exist."""
        seed_database(db_session)
        inserted_second = seed_database(db_session, skip_if_exists=False)
        assert inserted_second == len(SEED_PLANS)
        # Now double the plans in DB
        assert db_session.query(TravelPlan).count() == len(SEED_PLANS) * 2

    def test_seed_on_empty_db_returns_nonzero(self, db_session):
        assert db_session.query(TravelPlan).count() == 0
        inserted = seed_database(db_session)
        assert inserted > 0

    def test_places_have_nonblank_names(self, db_session):
        seed_database(db_session)
        places = db_session.query(Place).all()
        assert all(p.name.strip() for p in places)

    def test_estimated_costs_nonnegative(self, db_session):
        seed_database(db_session)
        places = db_session.query(Place).all()
        assert all(p.estimated_cost >= 0 for p in places)

    def test_expense_amounts_positive(self, db_session):
        seed_database(db_session)
        expenses = db_session.query(Expense).all()
        assert all(e.amount > 0 for e in expenses)

    def test_budgets_positive(self, db_session):
        seed_database(db_session)
        plans = db_session.query(TravelPlan).all()
        assert all(p.budget > 0 for p in plans)
