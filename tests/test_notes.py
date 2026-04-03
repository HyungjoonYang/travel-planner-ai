"""Tests for notes field on TravelPlan (task #26)."""
from fastapi.testclient import TestClient


PLAN_BASE = {
    "destination": "Tokyo",
    "start_date": "2026-06-01",
    "end_date": "2026-06-07",
    "budget": 3000.0,
}


# --- Create: notes field ---

class TestCreateWithNotes:
    def test_create_with_notes_returns_201(self, client: TestClient):
        r = client.post("/travel-plans", json={**PLAN_BASE, "notes": "Pack sunscreen"})
        assert r.status_code == 201

    def test_create_with_notes_persisted(self, client: TestClient):
        r = client.post("/travel-plans", json={**PLAN_BASE, "notes": "Pack sunscreen"})
        assert r.json()["notes"] == "Pack sunscreen"

    def test_create_without_notes_defaults_empty(self, client: TestClient):
        r = client.post("/travel-plans", json=PLAN_BASE)
        assert r.status_code == 201
        assert r.json()["notes"] == ""

    def test_notes_present_in_get_by_id(self, client: TestClient):
        plan_id = client.post("/travel-plans", json={**PLAN_BASE, "notes": "Visa required"}).json()["id"]
        r = client.get(f"/travel-plans/{plan_id}")
        assert r.json()["notes"] == "Visa required"

    def test_notes_multiline(self, client: TestClient):
        text = "Day 1: arrive\nDay 2: sightsee"
        r = client.post("/travel-plans", json={**PLAN_BASE, "notes": text})
        assert r.json()["notes"] == text


# --- PATCH: update notes ---

class TestPatchNotes:
    def test_patch_notes_updates_value(self, client: TestClient):
        plan_id = client.post("/travel-plans", json=PLAN_BASE).json()["id"]
        r = client.patch(f"/travel-plans/{plan_id}", json={"notes": "Bring adapter"})
        assert r.status_code == 200
        assert r.json()["notes"] == "Bring adapter"

    def test_patch_notes_persists_on_subsequent_get(self, client: TestClient):
        plan_id = client.post("/travel-plans", json=PLAN_BASE).json()["id"]
        client.patch(f"/travel-plans/{plan_id}", json={"notes": "Bring adapter"})
        r = client.get(f"/travel-plans/{plan_id}")
        assert r.json()["notes"] == "Bring adapter"

    def test_patch_notes_to_empty_string(self, client: TestClient):
        plan_id = client.post("/travel-plans", json={**PLAN_BASE, "notes": "something"}).json()["id"]
        r = client.patch(f"/travel-plans/{plan_id}", json={"notes": ""})
        assert r.json()["notes"] == ""

    def test_patch_other_field_preserves_notes(self, client: TestClient):
        plan_id = client.post("/travel-plans", json={**PLAN_BASE, "notes": "Keep me"}).json()["id"]
        client.patch(f"/travel-plans/{plan_id}", json={"budget": 9999.0})
        r = client.get(f"/travel-plans/{plan_id}")
        assert r.json()["notes"] == "Keep me"

    def test_patch_notes_404_on_missing_plan(self, client: TestClient):
        r = client.patch("/travel-plans/99999", json={"notes": "x"})
        assert r.status_code == 404


# --- GET /travel-plans?notes= filter ---

class TestNotesFilter:
    def _create(self, client: TestClient, notes="", destination="Tokyo"):
        return client.post("/travel-plans", json={**PLAN_BASE, "destination": destination, "notes": notes}).json()["id"]

    def test_filter_returns_matching_plan(self, client: TestClient):
        self._create(client, notes="bring umbrella")
        self._create(client, notes="sunny destination")
        r = client.get("/travel-plans?notes=umbrella")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["notes"] == "bring umbrella"

    def test_filter_case_insensitive(self, client: TestClient):
        self._create(client, notes="Bring Umbrella")
        r = client.get("/travel-plans?notes=umbrella")
        assert len(r.json()["items"]) == 1

    def test_filter_partial_match(self, client: TestClient):
        self._create(client, notes="remember to book hotel early")
        r = client.get("/travel-plans?notes=book hotel")
        assert len(r.json()["items"]) == 1

    def test_filter_no_match_returns_empty(self, client: TestClient):
        self._create(client, notes="beach vacation")
        r = client.get("/travel-plans?notes=mountain")
        assert r.json()["items"] == []
        assert r.json()["total"] == 0

    def test_filter_matches_multiple(self, client: TestClient):
        self._create(client, notes="visa needed")
        self._create(client, notes="check visa requirements")
        self._create(client, notes="no special docs")
        r = client.get("/travel-plans?notes=visa")
        assert len(r.json()["items"]) == 2

    def test_no_notes_filter_returns_all(self, client: TestClient):
        self._create(client, notes="a")
        self._create(client, notes="b")
        r = client.get("/travel-plans")
        assert r.json()["total"] == 2

    def test_notes_filter_composes_with_destination(self, client: TestClient):
        self._create(client, notes="visa needed", destination="Paris")
        self._create(client, notes="visa needed", destination="Berlin")
        r = client.get("/travel-plans?notes=visa&destination=Paris")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["destination"] == "Paris"

    def test_notes_filter_composes_with_status(self, client: TestClient):
        pid = self._create(client, notes="confirmed trip")
        client.patch(f"/travel-plans/{pid}", json={"status": "confirmed"})
        self._create(client, notes="confirmed trip")  # draft
        r = client.get("/travel-plans?notes=confirmed trip&status=confirmed")
        assert len(r.json()["items"]) == 1

    def test_notes_filter_reflected_in_total(self, client: TestClient):
        self._create(client, notes="adventure")
        self._create(client, notes="adventure time")
        self._create(client, notes="relaxing")
        r = client.get("/travel-plans?notes=adventure")
        assert r.json()["total"] == 2

    def test_notes_in_list_summary(self, client: TestClient):
        self._create(client, notes="summit hike")
        r = client.get("/travel-plans?notes=summit")
        assert r.json()["items"][0]["notes"] == "summit hike"


# --- Duplicate copies notes ---

class TestDuplicateCopiesNotes:
    def test_duplicate_preserves_notes(self, client: TestClient):
        pid = client.post("/travel-plans", json={**PLAN_BASE, "notes": "original notes"}).json()["id"]
        r = client.post(f"/travel-plans/{pid}/duplicate")
        assert r.status_code == 201
        assert r.json()["notes"] == "original notes"

    def test_duplicate_of_plan_without_notes(self, client: TestClient):
        pid = client.post("/travel-plans", json=PLAN_BASE).json()["id"]
        r = client.post(f"/travel-plans/{pid}/duplicate")
        assert r.json()["notes"] == ""

    def test_duplicate_notes_independent_of_original(self, client: TestClient):
        pid = client.post("/travel-plans", json={**PLAN_BASE, "notes": "original"}).json()["id"]
        dup_id = client.post(f"/travel-plans/{pid}/duplicate").json()["id"]
        client.patch(f"/travel-plans/{dup_id}", json={"notes": "modified copy"})
        r = client.get(f"/travel-plans/{pid}")
        assert r.json()["notes"] == "original"
