"""Tests for plan sharing endpoints.

Endpoints covered:
  POST   /travel-plans/{id}/share        → generate share token (201)
  DELETE /travel-plans/{id}/share        → revoke share (204)
  GET    /travel-plans/shared/{token}    → public read-only view (200)
"""

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-05-01",
    "end_date": "2026-05-07",
    "budget": 3000.0,
    "interests": "food,culture",
}


def create_plan(client, **overrides):
    payload = {**PLAN_PAYLOAD, **overrides}
    resp = client.post("/travel-plans", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ===========================================================================
# POST /travel-plans/{id}/share  — create share link
# ===========================================================================

class TestCreateShare:
    def test_returns_201(self, client):
        plan = create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/share")
        assert resp.status_code == 201

    def test_response_has_plan_id(self, client):
        plan = create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/share")
        assert resp.json()["plan_id"] == plan["id"]

    def test_response_has_token(self, client):
        plan = create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/share")
        token = resp.json()["token"]
        assert isinstance(token, str)
        assert len(token) > 10

    def test_response_has_share_url(self, client):
        plan = create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/share")
        share_url = resp.json()["share_url"]
        assert "shared" in share_url
        assert resp.json()["token"] in share_url

    def test_share_url_contains_token(self, client):
        plan = create_plan(client)
        resp = client.post(f"/travel-plans/{plan['id']}/share")
        data = resp.json()
        assert data["token"] in data["share_url"]

    def test_plan_is_shared_after_sharing(self, client):
        plan = create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/share")
        get_resp = client.get(f"/travel-plans/{plan['id']}")
        assert get_resp.json()["is_shared"] is True

    def test_plan_not_shared_by_default(self, client):
        plan = create_plan(client)
        get_resp = client.get(f"/travel-plans/{plan['id']}")
        assert get_resp.json()["is_shared"] is False

    def test_idempotent_returns_same_token(self, client):
        plan = create_plan(client)
        resp1 = client.post(f"/travel-plans/{plan['id']}/share")
        resp2 = client.post(f"/travel-plans/{plan['id']}/share")
        assert resp1.json()["token"] == resp2.json()["token"]

    def test_404_for_missing_plan(self, client):
        resp = client.post("/travel-plans/9999/share")
        assert resp.status_code == 404

    def test_404_detail_message(self, client):
        resp = client.post("/travel-plans/9999/share")
        assert "not found" in resp.json()["detail"].lower()

    def test_different_plans_get_different_tokens(self, client):
        plan1 = create_plan(client)
        plan2 = create_plan(client, destination="Paris")
        token1 = client.post(f"/travel-plans/{plan1['id']}/share").json()["token"]
        token2 = client.post(f"/travel-plans/{plan2['id']}/share").json()["token"]
        assert token1 != token2


# ===========================================================================
# DELETE /travel-plans/{id}/share  — revoke share
# ===========================================================================

class TestRevokeShare:
    def test_returns_204(self, client):
        plan = create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/share")
        resp = client.delete(f"/travel-plans/{plan['id']}/share")
        assert resp.status_code == 204

    def test_no_body_on_204(self, client):
        plan = create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/share")
        resp = client.delete(f"/travel-plans/{plan['id']}/share")
        assert resp.content == b""

    def test_plan_is_not_shared_after_revoke(self, client):
        plan = create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/share")
        client.delete(f"/travel-plans/{plan['id']}/share")
        get_resp = client.get(f"/travel-plans/{plan['id']}")
        assert get_resp.json()["is_shared"] is False

    def test_shared_link_returns_404_after_revoke(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        client.delete(f"/travel-plans/{plan['id']}/share")
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.status_code == 404

    def test_reshare_generates_new_token(self, client):
        plan = create_plan(client)
        token1 = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        client.delete(f"/travel-plans/{plan['id']}/share")
        token2 = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        assert token1 != token2

    def test_revoke_unshared_plan_is_204(self, client):
        plan = create_plan(client)
        resp = client.delete(f"/travel-plans/{plan['id']}/share")
        assert resp.status_code == 204

    def test_404_for_missing_plan(self, client):
        resp = client.delete("/travel-plans/9999/share")
        assert resp.status_code == 404


# ===========================================================================
# GET /travel-plans/shared/{token}  — public read-only view
# ===========================================================================

class TestGetSharedPlan:
    def test_returns_200(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.status_code == 200

    def test_returns_correct_plan(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.json()["id"] == plan["id"]

    def test_returns_destination(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.json()["destination"] == "Tokyo"

    def test_returns_is_shared_true(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.json()["is_shared"] is True

    def test_returns_itineraries(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert "itineraries" in resp.json()

    def test_returns_expenses(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert "expenses" in resp.json()

    def test_404_for_invalid_token(self, client):
        resp = client.get("/travel-plans/shared/invalid-token-xyz")
        assert resp.status_code == 404

    def test_404_detail_message(self, client):
        resp = client.get("/travel-plans/shared/bogus")
        assert "not found" in resp.json()["detail"].lower()

    def test_404_after_revoke(self, client):
        plan = create_plan(client)
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        client.delete(f"/travel-plans/{plan['id']}/share")
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.status_code == 404

    def test_plan_with_itinerary_accessible_via_share(self, client):
        plan = create_plan(client)
        client.post(
            f"/plans/{plan['id']}/itineraries",
            json={"date": "2026-05-01", "notes": "Day 1", "transport": "walk"},
        )
        token = client.post(f"/travel-plans/{plan['id']}/share").json()["token"]
        resp = client.get(f"/travel-plans/shared/{token}")
        assert resp.status_code == 200
        assert len(resp.json()["itineraries"]) == 1


# ===========================================================================
# is_shared field in list / get responses
# ===========================================================================

class TestIsSharedField:
    def test_is_shared_in_get_plan_response(self, client):
        plan = create_plan(client)
        resp = client.get(f"/travel-plans/{plan['id']}")
        assert "is_shared" in resp.json()

    def test_is_shared_in_list_response(self, client):
        create_plan(client)
        resp = client.get("/travel-plans")
        item = resp.json()["items"][0]
        assert "is_shared" in item

    def test_is_shared_false_in_list_by_default(self, client):
        create_plan(client)
        resp = client.get("/travel-plans")
        assert resp.json()["items"][0]["is_shared"] is False

    def test_is_shared_true_in_list_after_sharing(self, client):
        plan = create_plan(client)
        client.post(f"/travel-plans/{plan['id']}/share")
        resp = client.get("/travel-plans")
        assert resp.json()["items"][0]["is_shared"] is True
