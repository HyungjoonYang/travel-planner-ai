"""Tests for TravelPlan CRUD endpoints."""
from fastapi.testclient import TestClient


PLAN_PAYLOAD = {
    "destination": "Tokyo, Japan",
    "start_date": "2026-05-01",
    "end_date": "2026-05-07",
    "budget": 2000.0,
    "interests": "food,culture,temples",
    "status": "draft",
}


class TestCreateTravelPlan:
    def test_create_returns_201(self, client: TestClient):
        resp = client.post("/travel-plans", json=PLAN_PAYLOAD)
        assert resp.status_code == 201

    def test_create_response_fields(self, client: TestClient):
        resp = client.post("/travel-plans", json=PLAN_PAYLOAD)
        data = resp.json()
        assert data["destination"] == "Tokyo, Japan"
        assert data["budget"] == 2000.0
        assert data["status"] == "draft"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_invalid_status(self, client: TestClient):
        payload = {**PLAN_PAYLOAD, "status": "invalid"}
        resp = client.post("/travel-plans", json=payload)
        assert resp.status_code == 422

    def test_create_invalid_budget(self, client: TestClient):
        payload = {**PLAN_PAYLOAD, "budget": -100}
        resp = client.post("/travel-plans", json=payload)
        assert resp.status_code == 422

    def test_create_missing_destination(self, client: TestClient):
        payload = {k: v for k, v in PLAN_PAYLOAD.items() if k != "destination"}
        resp = client.post("/travel-plans", json=payload)
        assert resp.status_code == 422


class TestListTravelPlans:
    def test_list_empty(self, client: TestClient):
        resp = client.get("/travel-plans")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_list_after_create(self, client: TestClient):
        client.post("/travel-plans", json=PLAN_PAYLOAD)
        resp = client.get("/travel-plans")
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert len(data) == 1
        assert data[0]["destination"] == "Tokyo, Japan"

    def test_list_multiple(self, client: TestClient):
        client.post("/travel-plans", json=PLAN_PAYLOAD)
        second = {**PLAN_PAYLOAD, "destination": "Paris, France"}
        client.post("/travel-plans", json=second)
        resp = client.get("/travel-plans")
        assert len(resp.json()["items"]) == 2


class TestGetTravelPlan:
    def test_get_existing(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.get(f"/travel-plans/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_not_found(self, client: TestClient):
        resp = client.get("/travel-plans/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Travel plan not found"

    def test_get_includes_relations(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.get(f"/travel-plans/{created['id']}")
        data = resp.json()
        assert "itineraries" in data
        assert "expenses" in data


class TestUpdateTravelPlan:
    def test_patch_destination(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.patch(
            f"/travel-plans/{created['id']}", json={"destination": "Osaka, Japan"}
        )
        assert resp.status_code == 200
        assert resp.json()["destination"] == "Osaka, Japan"

    def test_patch_status(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.patch(
            f"/travel-plans/{created['id']}", json={"status": "confirmed"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    def test_patch_preserves_other_fields(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.patch(
            f"/travel-plans/{created['id']}", json={"destination": "Kyoto"}
        )
        data = resp.json()
        assert data["budget"] == PLAN_PAYLOAD["budget"]
        assert data["interests"] == PLAN_PAYLOAD["interests"]

    def test_patch_not_found(self, client: TestClient):
        resp = client.patch("/travel-plans/9999", json={"destination": "Nowhere"})
        assert resp.status_code == 404

    def test_patch_invalid_status(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.patch(
            f"/travel-plans/{created['id']}", json={"status": "bad-value"}
        )
        assert resp.status_code == 422


class TestDeleteTravelPlan:
    def test_delete_returns_204(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        resp = client.delete(f"/travel-plans/{created['id']}")
        assert resp.status_code == 204

    def test_delete_removes_from_list(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        client.delete(f"/travel-plans/{created['id']}")
        resp = client.get("/travel-plans")
        assert resp.json()["items"] == []

    def test_delete_not_found(self, client: TestClient):
        resp = client.delete("/travel-plans/9999")
        assert resp.status_code == 404

    def test_delete_then_get_not_found(self, client: TestClient):
        created = client.post("/travel-plans", json=PLAN_PAYLOAD).json()
        client.delete(f"/travel-plans/{created['id']}")
        resp = client.get(f"/travel-plans/{created['id']}")
        assert resp.status_code == 404
