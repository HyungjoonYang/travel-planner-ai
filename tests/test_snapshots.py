"""Tests for Plan version history — POST/GET /travel-plans/{id}/snapshot(s)."""


PLAN_PAYLOAD = {
    "destination": "Kyoto",
    "start_date": "2026-05-01",
    "end_date": "2026-05-03",
    "budget": 2000.0,
    "interests": "culture,food",
    "status": "draft",
}


def _create_plan(client):
    r = client.post("/travel-plans", json=PLAN_PAYLOAD)
    assert r.status_code == 201
    return r.json()["id"]


# ---------------------------------------------------------------------------
# POST /travel-plans/{id}/snapshot
# ---------------------------------------------------------------------------

class TestCreateSnapshot:
    def test_returns_201(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.status_code == 201

    def test_response_has_id(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert "id" in r.json()

    def test_response_travel_plan_id(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.json()["travel_plan_id"] == pid

    def test_response_has_created_at(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.json()["created_at"] is not None

    def test_label_none_by_default(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.json()["label"] is None

    def test_label_stored(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={"label": "before Tokyo"})
        assert r.json()["label"] == "before Tokyo"

    def test_label_too_long_returns_422(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={"label": "x" * 101})
        assert r.status_code == 422

    def test_snapshot_data_is_dict(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert isinstance(r.json()["snapshot_data"], dict)

    def test_snapshot_data_has_destination(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.json()["snapshot_data"]["destination"] == "Kyoto"

    def test_snapshot_data_has_id(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.json()["snapshot_data"]["id"] == pid

    def test_snapshot_data_has_budget(self, client):
        pid = _create_plan(client)
        r = client.post(f"/travel-plans/{pid}/snapshot", json={})
        assert r.json()["snapshot_data"]["budget"] == 2000.0

    def test_404_on_unknown_plan(self, client):
        r = client.post("/travel-plans/9999/snapshot", json={})
        assert r.status_code == 404

    def test_snapshot_data_frozen_after_plan_update(self, client):
        """Snapshot captures state at creation time; subsequent plan edits don't affect it."""
        pid = _create_plan(client)
        snap_r = client.post(f"/travel-plans/{pid}/snapshot", json={"label": "v1"})
        snap_id = snap_r.json()["id"]

        # Update the plan destination
        client.patch(f"/travel-plans/{pid}", json={"destination": "Osaka"})

        # Fetch snapshot — should still show original destination
        r = client.get(f"/travel-plans/{pid}/snapshots/{snap_id}")
        assert r.json()["snapshot_data"]["destination"] == "Kyoto"


# ---------------------------------------------------------------------------
# GET /travel-plans/{id}/snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:
    def test_returns_200(self, client):
        pid = _create_plan(client)
        r = client.get(f"/travel-plans/{pid}/snapshots")
        assert r.status_code == 200

    def test_empty_initially(self, client):
        pid = _create_plan(client)
        r = client.get(f"/travel-plans/{pid}/snapshots")
        assert r.json() == []

    def test_one_snapshot_after_post(self, client):
        pid = _create_plan(client)
        client.post(f"/travel-plans/{pid}/snapshot", json={})
        r = client.get(f"/travel-plans/{pid}/snapshots")
        assert len(r.json()) == 1

    def test_two_snapshots_after_two_posts(self, client):
        pid = _create_plan(client)
        client.post(f"/travel-plans/{pid}/snapshot", json={})
        client.post(f"/travel-plans/{pid}/snapshot", json={"label": "v2"})
        r = client.get(f"/travel-plans/{pid}/snapshots")
        assert len(r.json()) == 2

    def test_summary_fields_present(self, client):
        pid = _create_plan(client)
        client.post(f"/travel-plans/{pid}/snapshot", json={"label": "check"})
        item = client.get(f"/travel-plans/{pid}/snapshots").json()[0]
        assert "id" in item
        assert "travel_plan_id" in item
        assert "created_at" in item
        assert "label" in item

    def test_summary_has_no_snapshot_data(self, client):
        """List endpoint returns lightweight summary without snapshot_data."""
        pid = _create_plan(client)
        client.post(f"/travel-plans/{pid}/snapshot", json={})
        item = client.get(f"/travel-plans/{pid}/snapshots").json()[0]
        assert "snapshot_data" not in item

    def test_404_on_unknown_plan(self, client):
        r = client.get("/travel-plans/9999/snapshots")
        assert r.status_code == 404

    def test_snapshots_isolated_between_plans(self, client):
        pid1 = _create_plan(client)
        pid2 = _create_plan(client)
        client.post(f"/travel-plans/{pid1}/snapshot", json={})
        r = client.get(f"/travel-plans/{pid2}/snapshots")
        assert r.json() == []

    def test_label_in_list(self, client):
        pid = _create_plan(client)
        client.post(f"/travel-plans/{pid}/snapshot", json={"label": "my-label"})
        item = client.get(f"/travel-plans/{pid}/snapshots").json()[0]
        assert item["label"] == "my-label"


# ---------------------------------------------------------------------------
# GET /travel-plans/{id}/snapshots/{snap_id}
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    def test_returns_200(self, client):
        pid = _create_plan(client)
        snap_id = client.post(f"/travel-plans/{pid}/snapshot", json={}).json()["id"]
        r = client.get(f"/travel-plans/{pid}/snapshots/{snap_id}")
        assert r.status_code == 200

    def test_has_snapshot_data(self, client):
        pid = _create_plan(client)
        snap_id = client.post(f"/travel-plans/{pid}/snapshot", json={}).json()["id"]
        r = client.get(f"/travel-plans/{pid}/snapshots/{snap_id}")
        assert "snapshot_data" in r.json()

    def test_snapshot_data_is_dict(self, client):
        pid = _create_plan(client)
        snap_id = client.post(f"/travel-plans/{pid}/snapshot", json={}).json()["id"]
        r = client.get(f"/travel-plans/{pid}/snapshots/{snap_id}")
        assert isinstance(r.json()["snapshot_data"], dict)

    def test_correct_destination_in_data(self, client):
        pid = _create_plan(client)
        snap_id = client.post(f"/travel-plans/{pid}/snapshot", json={}).json()["id"]
        r = client.get(f"/travel-plans/{pid}/snapshots/{snap_id}")
        assert r.json()["snapshot_data"]["destination"] == "Kyoto"

    def test_404_on_unknown_snap(self, client):
        pid = _create_plan(client)
        r = client.get(f"/travel-plans/{pid}/snapshots/9999")
        assert r.status_code == 404

    def test_404_on_unknown_plan(self, client):
        r = client.get("/travel-plans/9999/snapshots/1")
        assert r.status_code == 404

    def test_404_when_snap_belongs_to_different_plan(self, client):
        """Cannot fetch a snapshot using another plan's ID."""
        pid1 = _create_plan(client)
        pid2 = _create_plan(client)
        snap_id = client.post(f"/travel-plans/{pid1}/snapshot", json={}).json()["id"]
        r = client.get(f"/travel-plans/{pid2}/snapshots/{snap_id}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------

class TestSnapshotCascadeDelete:
    def test_snapshots_deleted_with_plan(self, client):
        """Deleting a travel plan cascades to its snapshots."""
        pid = _create_plan(client)
        client.post(f"/travel-plans/{pid}/snapshot", json={}).json()["id"]

        # Delete the plan
        assert client.delete(f"/travel-plans/{pid}").status_code == 204

        # Plan is gone; attempting to list snapshots returns 404
        r = client.get(f"/travel-plans/{pid}/snapshots")
        assert r.status_code == 404
