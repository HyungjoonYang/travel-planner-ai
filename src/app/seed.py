"""Seed the database with sample travel plan data for development/demo."""

import copy
from datetime import date

from sqlalchemy.orm import Session

from app.models import DayItinerary, Expense, Place, TravelPlan


SEED_PLANS = [
    {
        "destination": "Tokyo, Japan",
        "start_date": date(2026, 5, 1),
        "end_date": date(2026, 5, 5),
        "budget": 1_500_000.0,
        "interests": "food,culture,shopping",
        "status": "confirmed",
        "itineraries": [
            {
                "date": date(2026, 5, 1),
                "notes": "Arrive at Narita, check in, evening stroll in Shinjuku",
                "transport": "Narita Express → hotel",
                "places": [
                    {
                        "name": "Shinjuku Gyoen National Garden",
                        "category": "sightseeing",
                        "address": "11 Naitomachi, Shinjuku City, Tokyo",
                        "estimated_cost": 500.0,
                        "ai_reason": "Beautiful Japanese garden perfect for first-day relaxation after travel",
                        "order": 0,
                    },
                    {
                        "name": "Omoide Yokocho (Memory Lane)",
                        "category": "food",
                        "address": "1-chome, Shinjuku, Tokyo",
                        "estimated_cost": 3_000.0,
                        "ai_reason": "Iconic alley of yakitori stalls — authentic local dinner experience",
                        "order": 1,
                    },
                ],
            },
            {
                "date": date(2026, 5, 2),
                "notes": "Traditional culture day in Asakusa",
                "transport": "Tokyo Metro Ginza Line",
                "places": [
                    {
                        "name": "Senso-ji Temple",
                        "category": "sightseeing",
                        "address": "2-3-1 Asakusa, Taito City, Tokyo",
                        "estimated_cost": 0.0,
                        "ai_reason": "Tokyo's oldest temple — free entry, stunning architecture",
                        "order": 0,
                    },
                    {
                        "name": "Nakamise Shopping Street",
                        "category": "shopping",
                        "address": "Asakusa, Taito City, Tokyo",
                        "estimated_cost": 5_000.0,
                        "ai_reason": "Traditional souvenir shopping with local snacks",
                        "order": 1,
                    },
                    {
                        "name": "Kaminarimon (Thunder Gate)",
                        "category": "sightseeing",
                        "address": "2-1 Asakusa, Taito City, Tokyo",
                        "estimated_cost": 0.0,
                        "ai_reason": "Iconic gate — must-see photo spot",
                        "order": 2,
                    },
                ],
            },
        ],
        "expenses": [
            {
                "name": "Round-trip flight (Seoul → Tokyo)",
                "amount": 350_000.0,
                "category": "transport",
                "date": date(2026, 5, 1),
                "notes": "Booked via Korean Air",
            },
            {
                "name": "Hotel (4 nights)",
                "amount": 480_000.0,
                "category": "lodging",
                "date": date(2026, 5, 1),
                "notes": "Shinjuku area business hotel",
            },
        ],
    },
    {
        "destination": "Paris, France",
        "start_date": date(2026, 6, 10),
        "end_date": date(2026, 6, 16),
        "budget": 3_000.0,
        "interests": "art,food,history",
        "status": "draft",
        "itineraries": [
            {
                "date": date(2026, 6, 10),
                "notes": "Arrival day — iconic landmarks",
                "transport": "CDG Express → Gare du Nord",
                "places": [
                    {
                        "name": "Eiffel Tower",
                        "category": "sightseeing",
                        "address": "Champ de Mars, 5 Av. Anatole France, Paris",
                        "estimated_cost": 28.0,
                        "ai_reason": "Paris landmark — book summit tickets in advance to avoid queues",
                        "order": 0,
                    },
                    {
                        "name": "Champs-Élysées",
                        "category": "shopping",
                        "address": "Avenue des Champs-Élysées, Paris",
                        "estimated_cost": 50.0,
                        "ai_reason": "World-famous avenue for evening stroll and window shopping",
                        "order": 1,
                    },
                ],
            },
            {
                "date": date(2026, 6, 11),
                "notes": "Art & culture day",
                "transport": "Paris Métro Line 1",
                "places": [
                    {
                        "name": "Louvre Museum",
                        "category": "sightseeing",
                        "address": "Rue de Rivoli, 75001 Paris",
                        "estimated_cost": 17.0,
                        "ai_reason": "World's largest art museum — home to the Mona Lisa",
                        "order": 0,
                    },
                    {
                        "name": "Café de Flore",
                        "category": "cafe",
                        "address": "172 Bd Saint-Germain, 75006 Paris",
                        "estimated_cost": 15.0,
                        "ai_reason": "Historic Parisian café frequented by Sartre and Simone de Beauvoir",
                        "order": 1,
                    },
                ],
            },
        ],
        "expenses": [
            {
                "name": "Round-trip flight (Seoul → Paris)",
                "amount": 1_200.0,
                "category": "transport",
                "date": date(2026, 6, 10),
                "notes": "Booked via Air France",
            },
        ],
    },
]


def seed_database(db: Session, *, skip_if_exists: bool = True) -> int:
    """Populate the database with sample travel plans.

    Args:
        db: Active SQLAlchemy session.
        skip_if_exists: If True, skip seeding when TravelPlan rows already exist.

    Returns:
        Number of TravelPlan rows inserted (0 if skipped).
    """
    if skip_if_exists and db.query(TravelPlan).count() > 0:
        return 0

    inserted = 0
    for plan_data in copy.deepcopy(SEED_PLANS):
        itineraries_data = plan_data.pop("itineraries")
        expenses_data = plan_data.pop("expenses")

        plan = TravelPlan(**plan_data)
        db.add(plan)
        db.flush()  # get plan.id

        for itin_data in itineraries_data:
            places_data = itin_data.pop("places")
            itin = DayItinerary(travel_plan_id=plan.id, **itin_data)
            db.add(itin)
            db.flush()

            for place_data in places_data:
                place = Place(day_itinerary_id=itin.id, **place_data)
                db.add(place)

        for expense_data in expenses_data:
            expense = Expense(travel_plan_id=plan.id, **expense_data)
            db.add(expense)

        inserted += 1

    db.commit()
    return inserted
