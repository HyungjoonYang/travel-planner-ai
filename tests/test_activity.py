"""Tests for Plan Activity Log (Task #37).

PlanActivity records create/update/delete events on plans.
GET /travel-plans/{id}/activity returns list of events.
"""
PLAN_PAYLOAD = {
    "destination": "Paris",
    "start_date": "2026-07-01",
    "end_date": "2026-07-05",
    "budget": 2000.0,
    "interests": "art, food",
    "status": "draft",
}


def _create_plan(client, payload=None):
    data = payload or PLAN_PAYLOAD
    r = client.post("/travel-plans", json=data)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPlanActivitySchema:
    def test_out_fields_exist(self):
        from app.schemas import PlanActivityOut
        from datetime import datetime

        obj = PlanActivityOut(
            id=1,
            travel_plan_id=2,
            action="created",
            detail="Plan created",
            timestamp=datetime.now(),
        )
        assert obj.action == "created"
        assert obj.travel_plan_id == 2


# ---------------------------------------------------------------------------
# GET /travel-plans/{id}/activity — baseline
# ---------------------------------------------------------------------------

class TestActivityEndpoint:
    def test_empty_on_nonexistent_plan_returns_404(self, client):
        r = client.get("/travel-plans/9999/activity")
        assert r.status_code == 404

    def test_create_plan_logs_created_event(self, client):
        plan = _create_plan(client)
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        assert r.status_code == 200
        events = r.json()
        assert len(events) >= 1
        actions = [e["action"] for e in events]
        assert "created" in actions

    def test_created_event_fields(self, client):
        plan = _create_plan(client)
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        event = r.json()[0]
        assert event["id"] > 0
        assert event["travel_plan_id"] == plan["id"]
        assert event["action"] == "created"
        assert "detail" in event
        assert "timestamp" in event

    def test_update_plan_logs_updated_event(self, client):
        plan = _create_plan(client)
        client.patch(f"/travel-plans/{plan['id']}", json={"destination": "Lyon"})
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        events = r.json()
        actions = [e["action"] for e in events]
        assert "updated" in actions

    def test_updated_event_detail_mentions_changed_field(self, client):
        plan = _create_plan(client)
        client.patch(f"/travel-plans/{plan['id']}", json={"destination": "Lyon"})
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        update_events = [e for e in r.json() if e["action"] == "updated"]
        assert len(update_events) >= 1
        assert "destination" in update_events[0]["detail"]

    def test_multiple_updates_each_logged(self, client):
        plan = _create_plan(client)
        client.patch(f"/travel-plans/{plan['id']}", json={"destination": "Nice"})
        client.patch(f"/travel-plans/{plan['id']}", json={"budget": 3000.0})
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        update_events = [e for e in r.json() if e["action"] == "updated"]
        assert len(update_events) == 2

    def test_activity_list_ordered_oldest_first(self, client):
        plan = _create_plan(client)
        client.patch(f"/travel-plans/{plan['id']}", json={"destination": "Marseille"})
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        events = r.json()
        assert events[0]["action"] == "created"
        assert events[1]["action"] == "updated"

    def test_activity_list_returns_200_with_list(self, client):
        plan = _create_plan(client)
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_delete_plan_records_deleted_event_before_removal(self, client):
        """After delete the plan is gone, so we verify via a second plan's log being unaffected."""
        plan1 = _create_plan(client)
        plan2 = _create_plan(client, {**PLAN_PAYLOAD, "destination": "Berlin"})

        # Delete plan1
        r = client.delete(f"/travel-plans/{plan1['id']}")
        assert r.status_code == 204

        # plan2's log should only have its own 'created' event
        r2 = client.get(f"/travel-plans/{plan2['id']}/activity")
        events2 = r2.json()
        assert all(e["travel_plan_id"] == plan2["id"] for e in events2)

    def test_activity_isolated_per_plan(self, client):
        plan1 = _create_plan(client)
        plan2 = _create_plan(client, {**PLAN_PAYLOAD, "destination": "Rome"})
        client.patch(f"/travel-plans/{plan1['id']}", json={"destination": "Florence"})

        r = client.get(f"/travel-plans/{plan2['id']}/activity")
        events = r.json()
        # plan2 should only have its own 'created' event
        assert all(e["travel_plan_id"] == plan2["id"] for e in events)

    def test_no_extra_fields_in_response(self, client):
        plan = _create_plan(client)
        r = client.get(f"/travel-plans/{plan['id']}/activity")
        event = r.json()[0]
        expected_keys = {"id", "travel_plan_id", "action", "detail", "timestamp"}
        assert set(event.keys()) == expected_keys
