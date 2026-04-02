"""Tests for #28 — tags field on TravelPlan and GET /travel-plans?tag= filter."""
import json

from fastapi.testclient import TestClient

BASE_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-06-01",
    "end_date": "2026-06-07",
    "budget": 2000.0,
}


def make_plan(client: TestClient, **kwargs):
    payload = {**BASE_PAYLOAD, **kwargs}
    r = client.post("/travel-plans", json=payload)
    assert r.status_code == 201
    return r.json()


# --- Create with tags ---

class TestCreateTags:
    def test_create_with_tags_returns_tags(self, client: TestClient):
        plan = make_plan(client, tags="beach,food")
        assert plan["tags"] == "beach,food"

    def test_create_without_tags_defaults_empty(self, client: TestClient):
        plan = make_plan(client)
        assert plan["tags"] == ""

    def test_create_single_tag(self, client: TestClient):
        plan = make_plan(client, tags="culture")
        assert plan["tags"] == "culture"

    def test_create_many_tags(self, client: TestClient):
        plan = make_plan(client, tags="beach,food,culture,nature,history")
        assert plan["tags"] == "beach,food,culture,nature,history"

    def test_tags_in_get_single(self, client: TestClient):
        plan = make_plan(client, tags="hiking")
        r = client.get(f"/travel-plans/{plan['id']}")
        assert r.status_code == 200
        assert r.json()["tags"] == "hiking"


# --- PATCH tags ---

class TestPatchTags:
    def test_patch_sets_tags(self, client: TestClient):
        plan = make_plan(client)
        r = client.patch(f"/travel-plans/{plan['id']}", json={"tags": "adventure"})
        assert r.status_code == 200
        assert r.json()["tags"] == "adventure"

    def test_patch_updates_existing_tags(self, client: TestClient):
        plan = make_plan(client, tags="old,tag")
        r = client.patch(f"/travel-plans/{plan['id']}", json={"tags": "new,tags,here"})
        assert r.status_code == 200
        assert r.json()["tags"] == "new,tags,here"

    def test_patch_clears_tags(self, client: TestClient):
        plan = make_plan(client, tags="beach")
        r = client.patch(f"/travel-plans/{plan['id']}", json={"tags": ""})
        assert r.status_code == 200
        assert r.json()["tags"] == ""

    def test_patch_other_field_preserves_tags(self, client: TestClient):
        plan = make_plan(client, tags="beach,food")
        r = client.patch(f"/travel-plans/{plan['id']}", json={"budget": 3000.0})
        assert r.status_code == 200
        assert r.json()["tags"] == "beach,food"


# --- GET /travel-plans?tag= filter ---

class TestTagFilter:
    def test_tag_filter_returns_matching_plan(self, client: TestClient):
        plan = make_plan(client, tags="beach,food")
        r = client.get("/travel-plans?tag=beach")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids

    def test_tag_filter_excludes_non_matching(self, client: TestClient):
        plan_yes = make_plan(client, tags="beach")
        plan_no = make_plan(client, tags="mountain,forest")
        r = client.get("/travel-plans?tag=beach")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan_yes["id"] in ids
        assert plan_no["id"] not in ids

    def test_tag_filter_case_insensitive_tag_value(self, client: TestClient):
        plan = make_plan(client, tags="Beach,Food")
        r = client.get("/travel-plans?tag=beach")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids

    def test_tag_filter_case_insensitive_query(self, client: TestClient):
        plan = make_plan(client, tags="beach")
        r = client.get("/travel-plans?tag=BEACH")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids

    def test_tag_filter_middle_tag(self, client: TestClient):
        plan = make_plan(client, tags="food,beach,culture")
        r = client.get("/travel-plans?tag=beach")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids

    def test_tag_filter_last_tag(self, client: TestClient):
        plan = make_plan(client, tags="food,culture,beach")
        r = client.get("/travel-plans?tag=beach")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids

    def test_tag_filter_exact_match_not_substring(self, client: TestClient):
        """'sea' should not match a plan that only has 'seaside'."""
        plan_no = make_plan(client, tags="seaside")
        plan_yes = make_plan(client, tags="sea")
        r = client.get("/travel-plans?tag=sea")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan_yes["id"] in ids
        assert plan_no["id"] not in ids

    def test_tag_filter_no_matches_returns_empty(self, client: TestClient):
        r = client.get("/travel-plans?tag=xyznonexistenttag999")
        assert r.json()["total"] == 0
        assert r.json()["items"] == []

    def test_tag_filter_no_param_returns_all(self, client: TestClient):
        plan = make_plan(client, tags="beach")
        r = client.get("/travel-plans")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids

    def test_tag_filter_combined_with_destination(self, client: TestClient):
        plan = make_plan(client, destination="UniqueTagCity", tags="beach,food")
        r = client.get("/travel-plans?tag=beach&destination=UniqueTagCity")
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["id"] == plan["id"]

    def test_tag_filter_combined_with_status(self, client: TestClient):
        plan_conf = make_plan(client, tags="adventure", status="confirmed")
        make_plan(client, tags="adventure", status="draft")
        r = client.get("/travel-plans?tag=adventure&status=confirmed")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan_conf["id"] in ids
        assert all(p["status"] == "confirmed" for p in r.json()["items"])

    def test_tag_filter_single_tag_field(self, client: TestClient):
        plan = make_plan(client, tags="solo")
        r = client.get("/travel-plans?tag=solo")
        ids = [p["id"] for p in r.json()["items"]]
        assert plan["id"] in ids


# --- Tags in duplicate ---

class TestDuplicateCopiesTags:
    def test_duplicate_copies_tags(self, client: TestClient):
        original = make_plan(client, tags="beach,food")
        r = client.post(f"/travel-plans/{original['id']}/duplicate")
        assert r.status_code == 201
        assert r.json()["tags"] == "beach,food"

    def test_duplicate_empty_tags(self, client: TestClient):
        original = make_plan(client, tags="")
        r = client.post(f"/travel-plans/{original['id']}/duplicate")
        assert r.status_code == 201
        assert r.json()["tags"] == ""


# --- Tags in export ---

class TestExportIncludesTags:
    def test_export_includes_tags(self, client: TestClient):
        plan = make_plan(client, tags="adventure,hiking")
        r = client.get(f"/travel-plans/{plan['id']}/export")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data["tags"] == "adventure,hiking"


# --- Tags in list items (PaginatedPlans) ---

class TestTagsInListResponse:
    def test_list_items_include_tags(self, client: TestClient):
        make_plan(client, destination="UniqueTagListCity", tags="nature")
        r = client.get("/travel-plans?destination=UniqueTagListCity")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["tags"] == "nature"
