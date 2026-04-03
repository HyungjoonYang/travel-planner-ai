"""Tests for collaborative comments on shared plans (task #33).

Endpoints:
  POST   /travel-plans/shared/{token}/comments   — anonymous comment creation
  GET    /travel-plans/shared/{token}/comments   — list comments (oldest first)
  DELETE /travel-plans/{id}/comments/{cid}       — owner deletes a comment
"""



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Seoul",
    "start_date": "2026-06-01",
    "end_date": "2026-06-05",
    "budget": 2000.0,
}


def _create_plan(client):
    resp = client.post("/travel-plans", json=PLAN_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()


def _share_plan(client, plan_id: int) -> str:
    resp = client.post(f"/travel-plans/{plan_id}/share")
    assert resp.status_code == 201
    return resp.json()["token"]


def _make_comment(client, token: str, author: str = "Alice", text: str = "Looks great!"):
    return client.post(
        f"/travel-plans/shared/{token}/comments",
        json={"author_name": author, "text": text},
    )


# ---------------------------------------------------------------------------
# POST /travel-plans/shared/{token}/comments
# ---------------------------------------------------------------------------

class TestCreateComment:
    def test_201_on_valid_comment(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        resp = _make_comment(client, token)
        assert resp.status_code == 201

    def test_response_has_id(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        data = _make_comment(client, token).json()
        assert isinstance(data["id"], int)

    def test_response_author_name(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        data = _make_comment(client, token, author="Bob").json()
        assert data["author_name"] == "Bob"

    def test_response_text(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        data = _make_comment(client, token, text="Amazing trip!").json()
        assert data["text"] == "Amazing trip!"

    def test_response_travel_plan_id(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        data = _make_comment(client, token).json()
        assert data["travel_plan_id"] == plan["id"]

    def test_response_has_created_at(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        data = _make_comment(client, token).json()
        assert "created_at" in data

    def test_404_on_invalid_token(self, client):
        resp = _make_comment(client, "no-such-token")
        assert resp.status_code == 404

    def test_404_on_unshared_plan(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        # Revoke sharing
        client.delete(f"/travel-plans/{plan['id']}/share")
        resp = _make_comment(client, token)
        assert resp.status_code == 404

    def test_422_empty_author_name(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        resp = client.post(
            f"/travel-plans/shared/{token}/comments",
            json={"author_name": "", "text": "hello"},
        )
        assert resp.status_code == 422

    def test_422_empty_text(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        resp = client.post(
            f"/travel-plans/shared/{token}/comments",
            json={"author_name": "Alice", "text": ""},
        )
        assert resp.status_code == 422

    def test_422_missing_fields(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        resp = client.post(f"/travel-plans/shared/{token}/comments", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /travel-plans/shared/{token}/comments
# ---------------------------------------------------------------------------

class TestListComments:
    def test_200_empty_list(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        resp = client.get(f"/travel-plans/shared/{token}/comments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_created_comment(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        _make_comment(client, token, author="Alice", text="Nice!")
        comments = client.get(f"/travel-plans/shared/{token}/comments").json()
        assert len(comments) == 1
        assert comments[0]["author_name"] == "Alice"

    def test_multiple_comments_listed(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        _make_comment(client, token, author="Alice", text="First!")
        _make_comment(client, token, author="Bob", text="Second!")
        comments = client.get(f"/travel-plans/shared/{token}/comments").json()
        assert len(comments) == 2

    def test_oldest_first_order(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        _make_comment(client, token, author="Alice", text="First")
        _make_comment(client, token, author="Bob", text="Second")
        comments = client.get(f"/travel-plans/shared/{token}/comments").json()
        assert comments[0]["author_name"] == "Alice"
        assert comments[1]["author_name"] == "Bob"

    def test_comment_fields_in_list(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        _make_comment(client, token)
        c = client.get(f"/travel-plans/shared/{token}/comments").json()[0]
        for field in ("id", "travel_plan_id", "author_name", "text", "created_at"):
            assert field in c

    def test_404_on_invalid_token(self, client):
        resp = client.get("/travel-plans/shared/bad-token/comments")
        assert resp.status_code == 404

    def test_404_after_share_revoked(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        client.delete(f"/travel-plans/{plan['id']}/share")
        resp = client.get(f"/travel-plans/shared/{token}/comments")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /travel-plans/{id}/comments/{cid}
# ---------------------------------------------------------------------------

class TestDeleteComment:
    def test_204_on_success(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        comment = _make_comment(client, token).json()
        resp = client.delete(f"/travel-plans/{plan['id']}/comments/{comment['id']}")
        assert resp.status_code == 204

    def test_comment_gone_after_delete(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        comment = _make_comment(client, token).json()
        client.delete(f"/travel-plans/{plan['id']}/comments/{comment['id']}")
        comments = client.get(f"/travel-plans/shared/{token}/comments").json()
        assert all(c["id"] != comment["id"] for c in comments)

    def test_404_plan_not_found(self, client):
        resp = client.delete("/travel-plans/9999/comments/1")
        assert resp.status_code == 404

    def test_404_comment_not_found(self, client):
        plan = _create_plan(client)
        resp = client.delete(f"/travel-plans/{plan['id']}/comments/9999")
        assert resp.status_code == 404

    def test_404_comment_belongs_to_other_plan(self, client):
        plan1 = _create_plan(client)
        plan2 = _create_plan(client)
        token = _share_plan(client, plan1["id"])
        comment = _make_comment(client, token).json()
        # Attempt to delete plan1's comment via plan2
        resp = client.delete(f"/travel-plans/{plan2['id']}/comments/{comment['id']}")
        assert resp.status_code == 404

    def test_other_comments_unaffected(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        c1 = _make_comment(client, token, author="Alice", text="Keep").json()
        c2 = _make_comment(client, token, author="Bob", text="Delete").json()
        client.delete(f"/travel-plans/{plan['id']}/comments/{c2['id']}")
        comments = client.get(f"/travel-plans/shared/{token}/comments").json()
        assert len(comments) == 1
        assert comments[0]["id"] == c1["id"]


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------

class TestCommentCascade:
    def test_comments_deleted_with_plan(self, client):
        plan = _create_plan(client)
        token = _share_plan(client, plan["id"])
        _make_comment(client, token, author="Alice", text="Will be gone")
        client.delete(f"/travel-plans/{plan['id']}")
        # Create a new plan to verify no stale comments exist
        plan2 = _create_plan(client)
        token2 = _share_plan(client, plan2["id"])
        # Comments for the deleted plan should not appear
        comments = client.get(f"/travel-plans/shared/{token2}/comments").json()
        assert len(comments) == 0
