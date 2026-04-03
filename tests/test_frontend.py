"""Tests for frontend static file serving."""
from fastapi.testclient import TestClient


class TestFrontendServing:
    def test_root_returns_200(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_returns_html(self, client: TestClient):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_root_contains_app_title(self, client: TestClient):
        resp = client.get("/")
        assert b"Travel Planner AI" in resp.content

    def test_root_contains_nav(self, client: TestClient):
        resp = client.get("/")
        assert b"Plans" in resp.content

    def test_root_contains_search_link(self, client: TestClient):
        resp = client.get("/")
        assert b"Search" in resp.content

    def test_root_contains_new_plan_link(self, client: TestClient):
        resp = client.get("/")
        assert b"New Plan" in resp.content

    def test_root_contains_js_api_fetch(self, client: TestClient):
        resp = client.get("/")
        assert b"travel-plans" in resp.content

    def test_root_is_complete_html_document(self, client: TestClient):
        resp = client.get("/")
        content = resp.content
        assert b"<!DOCTYPE html>" in content
        assert b"</html>" in content

    def test_static_index_accessible(self, client: TestClient):
        resp = client.get("/static/index.html")
        assert resp.status_code == 200

    def test_static_index_is_html(self, client: TestClient):
        resp = client.get("/static/index.html")
        assert "text/html" in resp.headers["content-type"]
