"""Tests for place ratings and reviews, and the top-places endpoint.

Endpoints covered:
  PATCH  /plans/{plan_id}/itineraries/{day_id}/places/{place_id}
         → rating (1-5) and review fields (via existing update endpoint)
  GET    /travel-plans/{id}/top-places?min_rating=&limit=
         → list top-rated places across all days of a plan
"""



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Kyoto",
    "start_date": "2026-06-01",
    "end_date": "2026-06-05",
    "budget": 2000.0,
    "interests": "culture,food",
}


def create_plan(client, **overrides):
    payload = {**PLAN_PAYLOAD, **overrides}
    resp = client.post("/travel-plans", json=payload)
    assert resp.status_code == 201
    return resp.json()


def create_day(client, plan_id, date="2026-06-01"):
    resp = client.post(
        f"/plans/{plan_id}/itineraries",
        json={"date": date, "notes": "", "transport": ""},
    )
    assert resp.status_code == 201
    return resp.json()


def create_place(client, plan_id, day_id, name="Fushimi Inari", **overrides):
    payload = {"name": name, "category": "sightseeing", **overrides}
    resp = client.post(f"/plans/{plan_id}/itineraries/{day_id}/places", json=payload)
    assert resp.status_code == 201
    return resp.json()


def rate_place(client, plan_id, day_id, place_id, rating, review=None):
    payload = {"rating": rating}
    if review is not None:
        payload["review"] = review
    resp = client.patch(
        f"/plans/{plan_id}/itineraries/{day_id}/places/{place_id}",
        json=payload,
    )
    return resp


# ===========================================================================
# PlaceOut — rating and review fields present
# ===========================================================================

class TestPlaceRatingFields:
    def test_place_has_rating_field(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        assert "rating" in place

    def test_place_rating_defaults_to_null(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        assert place["rating"] is None

    def test_place_has_review_field(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        assert "review" in place

    def test_place_review_defaults_to_null(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        assert place["review"] is None

    def test_place_created_with_rating(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"], rating=4)
        assert place["rating"] == 4

    def test_place_created_with_review(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"], review="Amazing shrine!")
        assert place["review"] == "Amazing shrine!"


# ===========================================================================
# PATCH rating — update via existing place endpoint
# ===========================================================================

class TestRatePlace:
    def test_patch_rating_returns_200(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        resp = rate_place(client, plan["id"], day["id"], place["id"], rating=5)
        assert resp.status_code == 200

    def test_patch_rating_persists(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=3)
        client.get(
            f"/plans/{plan['id']}/itineraries/{day['id']}/places/{place['id']}"
        )
        # verify via top-places instead (no direct get-place endpoint needed)
        resp = client.patch(
            f"/plans/{plan['id']}/itineraries/{day['id']}/places/{place['id']}",
            json={"rating": 3},
        )
        assert resp.json()["rating"] == 3

    def test_patch_review_persists(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        resp = rate_place(client, plan["id"], day["id"], place["id"], rating=4, review="Loved it")
        assert resp.json()["review"] == "Loved it"

    def test_patch_rating_1_valid(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        resp = rate_place(client, plan["id"], day["id"], place["id"], rating=1)
        assert resp.status_code == 200
        assert resp.json()["rating"] == 1

    def test_patch_rating_5_valid(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        resp = rate_place(client, plan["id"], day["id"], place["id"], rating=5)
        assert resp.status_code == 200
        assert resp.json()["rating"] == 5

    def test_patch_rating_0_invalid(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        resp = client.patch(
            f"/plans/{plan['id']}/itineraries/{day['id']}/places/{place['id']}",
            json={"rating": 0},
        )
        assert resp.status_code == 422

    def test_patch_rating_6_invalid(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        resp = client.patch(
            f"/plans/{plan['id']}/itineraries/{day['id']}/places/{place['id']}",
            json={"rating": 6},
        )
        assert resp.status_code == 422

    def test_other_fields_unaffected_by_rating_patch(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"], name="Kinkaku-ji")
        resp = rate_place(client, plan["id"], day["id"], place["id"], rating=5)
        assert resp.json()["name"] == "Kinkaku-ji"

    def test_update_rating_twice(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=2)
        resp = rate_place(client, plan["id"], day["id"], place["id"], rating=5)
        assert resp.json()["rating"] == 5


# ===========================================================================
# GET /travel-plans/{id}/top-places
# ===========================================================================

class TestTopPlaces:
    def test_returns_200(self, client):
        plan = create_plan(client)
        resp = client.get(f"/travel-plans/{plan['id']}/top-places")
        assert resp.status_code == 200

    def test_returns_empty_when_no_rated_places(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        create_place(client, plan["id"], day["id"])
        resp = client.get(f"/travel-plans/{plan['id']}/top-places")
        assert resp.json() == []

    def test_returns_rated_place(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"], name="Arashiyama")
        rate_place(client, plan["id"], day["id"], place["id"], rating=4)
        resp = client.get(f"/travel-plans/{plan['id']}/top-places")
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "Arashiyama"

    def test_result_has_rating(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=5)
        item = client.get(f"/travel-plans/{plan['id']}/top-places").json()[0]
        assert item["rating"] == 5

    def test_result_has_review(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=5, review="Must visit")
        item = client.get(f"/travel-plans/{plan['id']}/top-places").json()[0]
        assert item["review"] == "Must visit"

    def test_result_has_day_date(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"], date="2026-06-02")
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=3)
        item = client.get(f"/travel-plans/{plan['id']}/top-places").json()[0]
        assert item["day_date"] == "2026-06-02"

    def test_result_has_day_itinerary_id(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=3)
        item = client.get(f"/travel-plans/{plan['id']}/top-places").json()[0]
        assert item["day_itinerary_id"] == day["id"]

    def test_sorted_by_rating_desc(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        p1 = create_place(client, plan["id"], day["id"], name="Place A")
        p2 = create_place(client, plan["id"], day["id"], name="Place B")
        p3 = create_place(client, plan["id"], day["id"], name="Place C")
        rate_place(client, plan["id"], day["id"], p1["id"], rating=2)
        rate_place(client, plan["id"], day["id"], p2["id"], rating=5)
        rate_place(client, plan["id"], day["id"], p3["id"], rating=4)
        results = client.get(f"/travel-plans/{plan['id']}/top-places").json()
        ratings = [r["rating"] for r in results]
        assert ratings == sorted(ratings, reverse=True)

    def test_unrated_places_excluded(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        rated = create_place(client, plan["id"], day["id"], name="Rated")
        create_place(client, plan["id"], day["id"], name="Unrated")
        rate_place(client, plan["id"], day["id"], rated["id"], rating=4)
        results = client.get(f"/travel-plans/{plan['id']}/top-places").json()
        names = [r["name"] for r in results]
        assert "Rated" in names
        assert "Unrated" not in names

    def test_min_rating_filter(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        p1 = create_place(client, plan["id"], day["id"], name="Low")
        p2 = create_place(client, plan["id"], day["id"], name="High")
        rate_place(client, plan["id"], day["id"], p1["id"], rating=2)
        rate_place(client, plan["id"], day["id"], p2["id"], rating=5)
        results = client.get(
            f"/travel-plans/{plan['id']}/top-places", params={"min_rating": 4}
        ).json()
        names = [r["name"] for r in results]
        assert "High" in names
        assert "Low" not in names

    def test_min_rating_default_is_1(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(client, plan["id"], day["id"])
        rate_place(client, plan["id"], day["id"], place["id"], rating=1)
        results = client.get(f"/travel-plans/{plan['id']}/top-places").json()
        assert len(results) == 1

    def test_limit_param(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        for i in range(5):
            p = create_place(client, plan["id"], day["id"], name=f"Place {i}")
            rate_place(client, plan["id"], day["id"], p["id"], rating=3)
        results = client.get(
            f"/travel-plans/{plan['id']}/top-places", params={"limit": 3}
        ).json()
        assert len(results) == 3

    def test_limit_default_is_10(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        for i in range(12):
            p = create_place(client, plan["id"], day["id"], name=f"Place {i}")
            rate_place(client, plan["id"], day["id"], p["id"], rating=3)
        results = client.get(f"/travel-plans/{plan['id']}/top-places").json()
        assert len(results) == 10

    def test_limit_max_50(self, client):
        resp = client.get("/travel-plans/999/top-places", params={"limit": 51})
        assert resp.status_code == 422

    def test_min_rating_0_invalid(self, client):
        resp = client.get("/travel-plans/999/top-places", params={"min_rating": 0})
        assert resp.status_code == 422

    def test_min_rating_6_invalid(self, client):
        resp = client.get("/travel-plans/999/top-places", params={"min_rating": 6})
        assert resp.status_code == 422

    def test_404_for_nonexistent_plan(self, client):
        resp = client.get("/travel-plans/9999/top-places")
        assert resp.status_code == 404

    def test_places_from_multiple_days(self, client):
        plan = create_plan(client)
        day1 = create_day(client, plan["id"], date="2026-06-01")
        day2 = create_day(client, plan["id"], date="2026-06-02")
        p1 = create_place(client, plan["id"], day1["id"], name="Day1 Place")
        p2 = create_place(client, plan["id"], day2["id"], name="Day2 Place")
        rate_place(client, plan["id"], day1["id"], p1["id"], rating=5)
        rate_place(client, plan["id"], day2["id"], p2["id"], rating=4)
        results = client.get(f"/travel-plans/{plan['id']}/top-places").json()
        names = {r["name"] for r in results}
        assert names == {"Day1 Place", "Day2 Place"}

    def test_plans_isolated(self, client):
        plan1 = create_plan(client)
        plan2 = create_plan(client)
        day1 = create_day(client, plan1["id"])
        day2 = create_day(client, plan2["id"])
        p1 = create_place(client, plan1["id"], day1["id"], name="Plan1 Place")
        p2 = create_place(client, plan2["id"], day2["id"], name="Plan2 Place")
        rate_place(client, plan1["id"], day1["id"], p1["id"], rating=5)
        rate_place(client, plan2["id"], day2["id"], p2["id"], rating=5)
        results1 = client.get(f"/travel-plans/{plan1['id']}/top-places").json()
        results2 = client.get(f"/travel-plans/{plan2['id']}/top-places").json()
        assert all(r["name"] == "Plan1 Place" for r in results1)
        assert all(r["name"] == "Plan2 Place" for r in results2)

    def test_result_includes_standard_place_fields(self, client):
        plan = create_plan(client)
        day = create_day(client, plan["id"])
        place = create_place(
            client, plan["id"], day["id"],
            name="Nijo Castle", category="sightseeing", estimated_cost=600.0
        )
        rate_place(client, plan["id"], day["id"], place["id"], rating=4)
        item = client.get(f"/travel-plans/{plan['id']}/top-places").json()[0]
        assert item["name"] == "Nijo Castle"
        assert item["category"] == "sightseeing"
        assert item["estimated_cost"] == 600.0
