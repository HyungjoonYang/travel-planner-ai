"""Tests for Favorite Places library endpoints (Task #36)."""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAV_PAYLOAD = {
    "name": "Senso-ji Temple",
    "category": "sightseeing",
    "address": "2-3-1 Asakusa, Taito City, Tokyo",
    "estimated_cost": 0.0,
    "ai_reason": "Iconic Buddhist temple in Asakusa",
    "notes": "Visit early morning to avoid crowds",
}

PLAN_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-06-01",
    "end_date": "2026-06-03",
    "budget": 1500.0,
    "interests": "culture",
    "status": "draft",
}

ITINERARY_PAYLOAD = {
    "date": "2026-06-01",
    "notes": "Day 1",
    "transport": "subway",
}

PLACE_PAYLOAD = {
    "name": "Tsukiji Outer Market",
    "category": "food",
    "address": "4-16-2 Tsukiji, Chuo City, Tokyo",
    "estimated_cost": 30.0,
    "ai_reason": "Famous fish market",
    "order": 0,
}


def _create_favorite(client, payload=None):
    data = payload or FAV_PAYLOAD
    r = client.post("/favorite-places", json=data)
    assert r.status_code == 201
    return r.json()


def _create_plan_with_place(client):
    """Create a plan → itinerary → place, return (plan_id, day_id, place_id)."""
    plan = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
    plan_id = plan["id"]
    day = client.post(f"/plans/{plan_id}/itineraries", json=ITINERARY_PAYLOAD).json()
    day_id = day["id"]
    place = client.post(f"/plans/{plan_id}/itineraries/{day_id}/places", json=PLACE_PAYLOAD).json()
    return plan_id, day_id, place["id"]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestFavoritePlaceSchemas:
    def test_create_requires_name(self):
        from pydantic import ValidationError
        from app.schemas import FavoritePlaceCreate

        with pytest.raises(ValidationError):
            FavoritePlaceCreate()

    def test_create_name_min_length(self):
        from pydantic import ValidationError
        from app.schemas import FavoritePlaceCreate

        with pytest.raises(ValidationError):
            FavoritePlaceCreate(name="")

    def test_create_estimated_cost_non_negative(self):
        from pydantic import ValidationError
        from app.schemas import FavoritePlaceCreate

        with pytest.raises(ValidationError):
            FavoritePlaceCreate(name="Place", estimated_cost=-1.0)

    def test_create_defaults(self):
        from app.schemas import FavoritePlaceCreate

        f = FavoritePlaceCreate(name="Park")
        assert f.category == ""
        assert f.address == ""
        assert f.estimated_cost == 0.0
        assert f.ai_reason == ""
        assert f.notes == ""


# ---------------------------------------------------------------------------
# POST /favorite-places
# ---------------------------------------------------------------------------

class TestCreateFavoritePlace:
    def test_create_returns_201(self, client):
        r = client.post("/favorite-places", json=FAV_PAYLOAD)
        assert r.status_code == 201

    def test_create_response_fields(self, client):
        r = client.post("/favorite-places", json=FAV_PAYLOAD)
        data = r.json()
        assert data["id"] > 0
        assert data["name"] == FAV_PAYLOAD["name"]
        assert data["category"] == FAV_PAYLOAD["category"]
        assert data["address"] == FAV_PAYLOAD["address"]
        assert data["estimated_cost"] == FAV_PAYLOAD["estimated_cost"]
        assert data["ai_reason"] == FAV_PAYLOAD["ai_reason"]
        assert data["notes"] == FAV_PAYLOAD["notes"]
        assert "created_at" in data

    def test_create_with_minimal_payload(self, client):
        r = client.post("/favorite-places", json={"name": "Ueno Park"})
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Ueno Park"
        assert data["category"] == ""
        assert data["estimated_cost"] == 0.0

    def test_create_missing_name_returns_422(self, client):
        r = client.post("/favorite-places", json={"category": "food"})
        assert r.status_code == 422

    def test_create_empty_name_returns_422(self, client):
        r = client.post("/favorite-places", json={"name": ""})
        assert r.status_code == 422

    def test_create_negative_cost_returns_422(self, client):
        r = client.post("/favorite-places", json={"name": "Place", "estimated_cost": -5.0})
        assert r.status_code == 422

    def test_multiple_favorites_get_different_ids(self, client):
        id1 = _create_favorite(client)["id"]
        id2 = _create_favorite(client, {**FAV_PAYLOAD, "name": "Another Place"})["id"]
        assert id1 != id2


# ---------------------------------------------------------------------------
# GET /favorite-places
# ---------------------------------------------------------------------------

class TestListFavoritePlaces:
    def test_empty_list(self, client):
        r = client.get("/favorite-places")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_created_favorites(self, client):
        _create_favorite(client)
        _create_favorite(client, {**FAV_PAYLOAD, "name": "Shinjuku Gyoen"})
        r = client.get("/favorite-places")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        names = {item["name"] for item in data}
        assert "Senso-ji Temple" in names
        assert "Shinjuku Gyoen" in names

    def test_list_order_is_by_id(self, client):
        fav1 = _create_favorite(client)
        fav2 = _create_favorite(client, {**FAV_PAYLOAD, "name": "Place B"})
        r = client.get("/favorite-places")
        items = r.json()
        assert items[0]["id"] == fav1["id"]
        assert items[1]["id"] == fav2["id"]


# ---------------------------------------------------------------------------
# GET /favorite-places/{id}
# ---------------------------------------------------------------------------

class TestGetFavoritePlace:
    def test_get_existing(self, client):
        created = _create_favorite(client)
        r = client.get(f"/favorite-places/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/favorite-places/9999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /favorite-places/{id}
# ---------------------------------------------------------------------------

class TestDeleteFavoritePlace:
    def test_delete_returns_204(self, client):
        fav = _create_favorite(client)
        r = client.delete(f"/favorite-places/{fav['id']}")
        assert r.status_code == 204

    def test_deleted_not_in_list(self, client):
        fav = _create_favorite(client)
        client.delete(f"/favorite-places/{fav['id']}")
        r = client.get("/favorite-places")
        assert r.json() == []

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/favorite-places/9999")
        assert r.status_code == 404

    def test_delete_only_removes_target(self, client):
        fav1 = _create_favorite(client)
        fav2 = _create_favorite(client, {**FAV_PAYLOAD, "name": "Other Place"})
        client.delete(f"/favorite-places/{fav1['id']}")
        r = client.get("/favorite-places")
        remaining = r.json()
        assert len(remaining) == 1
        assert remaining[0]["id"] == fav2["id"]


# ---------------------------------------------------------------------------
# POST /favorite-places/copy-from-itinerary
# ---------------------------------------------------------------------------

class TestCopyFromItinerary:
    def test_copy_returns_201(self, client):
        _, _, place_id = _create_plan_with_place(client)
        r = client.post("/favorite-places/copy-from-itinerary", json={"place_id": place_id})
        assert r.status_code == 201

    def test_copy_inherits_place_fields(self, client):
        _, _, place_id = _create_plan_with_place(client)
        r = client.post("/favorite-places/copy-from-itinerary", json={"place_id": place_id})
        data = r.json()
        assert data["name"] == PLACE_PAYLOAD["name"]
        assert data["category"] == PLACE_PAYLOAD["category"]
        assert data["address"] == PLACE_PAYLOAD["address"]
        assert data["estimated_cost"] == PLACE_PAYLOAD["estimated_cost"]
        assert data["ai_reason"] == PLACE_PAYLOAD["ai_reason"]
        assert "id" in data
        assert "created_at" in data

    def test_copy_with_notes(self, client):
        _, _, place_id = _create_plan_with_place(client)
        r = client.post(
            "/favorite-places/copy-from-itinerary",
            json={"place_id": place_id, "notes": "Great for breakfast"},
        )
        assert r.json()["notes"] == "Great for breakfast"

    def test_copy_default_notes_empty(self, client):
        _, _, place_id = _create_plan_with_place(client)
        r = client.post("/favorite-places/copy-from-itinerary", json={"place_id": place_id})
        assert r.json()["notes"] == ""

    def test_copy_nonexistent_place_returns_404(self, client):
        r = client.post("/favorite-places/copy-from-itinerary", json={"place_id": 9999})
        assert r.status_code == 404

    def test_copied_place_appears_in_list(self, client):
        _, _, place_id = _create_plan_with_place(client)
        client.post("/favorite-places/copy-from-itinerary", json={"place_id": place_id})
        r = client.get("/favorite-places")
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == PLACE_PAYLOAD["name"]

    def test_copy_missing_place_id_returns_422(self, client):
        r = client.post("/favorite-places/copy-from-itinerary", json={})
        assert r.status_code == 422
