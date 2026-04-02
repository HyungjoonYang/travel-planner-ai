"""Tests for budget overage alerts — task #31.

Coverage:
- BudgetSummary: over_budget + overage_pct fields (not over, exactly at, over)
- GET /travel-plans?over_budget=true / false filter
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import client  # noqa: F401 — fixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(client: TestClient, budget: float = 1000.0) -> int:
    resp = client.post("/travel-plans", json={
        "destination": "Budget City",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "budget": budget,
    })
    assert resp.status_code == 201
    return resp.json()["id"]


def _add_expense(client: TestClient, plan_id: int, amount: float) -> None:
    resp = client.post(f"/plans/{plan_id}/expenses", json={
        "name": "Test expense",
        "amount": amount,
        "category": "food",
    })
    assert resp.status_code == 201


def _summary(client: TestClient, plan_id: int) -> dict:
    resp = client.get(f"/plans/{plan_id}/expenses/summary")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# BudgetSummary: over_budget field
# ---------------------------------------------------------------------------

class TestBudgetSummaryFields:
    def test_over_budget_false_when_no_expenses(self, client: TestClient):
        pid = _make_plan(client)
        data = _summary(client, pid)
        assert data["over_budget"] is False

    def test_overage_pct_zero_when_no_expenses(self, client: TestClient):
        pid = _make_plan(client)
        data = _summary(client, pid)
        assert data["overage_pct"] == 0.0

    def test_over_budget_false_when_under_budget(self, client: TestClient):
        pid = _make_plan(client, budget=500.0)
        _add_expense(client, pid, 200.0)
        data = _summary(client, pid)
        assert data["over_budget"] is False

    def test_overage_pct_zero_when_under_budget(self, client: TestClient):
        pid = _make_plan(client, budget=500.0)
        _add_expense(client, pid, 200.0)
        data = _summary(client, pid)
        assert data["overage_pct"] == 0.0

    def test_over_budget_false_when_exactly_at_budget(self, client: TestClient):
        pid = _make_plan(client, budget=300.0)
        _add_expense(client, pid, 300.0)
        data = _summary(client, pid)
        assert data["over_budget"] is False

    def test_overage_pct_zero_when_exactly_at_budget(self, client: TestClient):
        pid = _make_plan(client, budget=300.0)
        _add_expense(client, pid, 300.0)
        data = _summary(client, pid)
        assert data["overage_pct"] == 0.0

    def test_over_budget_true_when_over(self, client: TestClient):
        pid = _make_plan(client, budget=100.0)
        _add_expense(client, pid, 150.0)
        data = _summary(client, pid)
        assert data["over_budget"] is True

    def test_overage_pct_correct_when_over(self, client: TestClient):
        pid = _make_plan(client, budget=100.0)
        _add_expense(client, pid, 150.0)
        data = _summary(client, pid)
        assert data["overage_pct"] == 50.0  # 50% over

    def test_overage_pct_calculation_multiple_expenses(self, client: TestClient):
        pid = _make_plan(client, budget=200.0)
        _add_expense(client, pid, 120.0)
        _add_expense(client, pid, 120.0)  # total=240, budget=200, overage=20%
        data = _summary(client, pid)
        assert data["over_budget"] is True
        assert data["overage_pct"] == 20.0

    def test_overage_pct_rounded_to_two_decimals(self, client: TestClient):
        # 301/300 → 0.3333...% over → rounded to 0.33
        pid = _make_plan(client, budget=300.0)
        _add_expense(client, pid, 301.0)
        data = _summary(client, pid)
        assert data["over_budget"] is True
        assert data["overage_pct"] == 0.33

    def test_summary_still_has_existing_fields(self, client: TestClient):
        pid = _make_plan(client, budget=500.0)
        _add_expense(client, pid, 100.0)
        data = _summary(client, pid)
        assert "plan_id" in data
        assert "budget" in data
        assert "total_spent" in data
        assert "remaining" in data
        assert "by_category" in data
        assert "expense_count" in data


# ---------------------------------------------------------------------------
# GET /travel-plans?over_budget=true/false filter
# ---------------------------------------------------------------------------

class TestOverBudgetFilter:
    def test_over_budget_true_returns_only_over_budget_plans(self, client: TestClient):
        # Plan A: over budget
        pid_a = _make_plan(client, budget=100.0)
        _add_expense(client, pid_a, 200.0)
        # Plan B: under budget
        pid_b = _make_plan(client, budget=500.0)
        _add_expense(client, pid_b, 100.0)

        resp = client.get("/travel-plans?over_budget=true")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid_a in ids
        assert pid_b not in ids

    def test_over_budget_false_excludes_over_budget_plans(self, client: TestClient):
        pid_over = _make_plan(client, budget=50.0)
        _add_expense(client, pid_over, 100.0)
        pid_ok = _make_plan(client, budget=500.0)
        _add_expense(client, pid_ok, 50.0)

        resp = client.get("/travel-plans?over_budget=false")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid_over not in ids
        assert pid_ok in ids

    def test_over_budget_false_includes_plans_with_no_expenses(self, client: TestClient):
        pid_empty = _make_plan(client, budget=200.0)  # no expenses

        resp = client.get("/travel-plans?over_budget=false")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid_empty in ids

    def test_over_budget_true_excludes_plans_with_no_expenses(self, client: TestClient):
        pid_empty = _make_plan(client, budget=200.0)  # no expenses

        resp = client.get("/travel-plans?over_budget=true")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid_empty not in ids

    def test_over_budget_true_excludes_exactly_at_budget(self, client: TestClient):
        pid = _make_plan(client, budget=100.0)
        _add_expense(client, pid, 100.0)

        resp = client.get("/travel-plans?over_budget=true")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid not in ids

    def test_over_budget_false_includes_exactly_at_budget(self, client: TestClient):
        pid = _make_plan(client, budget=100.0)
        _add_expense(client, pid, 100.0)

        resp = client.get("/travel-plans?over_budget=false")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid in ids

    def test_no_over_budget_param_returns_all(self, client: TestClient):
        pid_over = _make_plan(client, budget=50.0)
        _add_expense(client, pid_over, 100.0)
        pid_ok = _make_plan(client, budget=500.0)
        _add_expense(client, pid_ok, 50.0)

        resp = client.get("/travel-plans")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid_over in ids
        assert pid_ok in ids

    def test_over_budget_filter_combinable_with_destination(self, client: TestClient):
        pid_paris_over = _make_plan(client, budget=100.0)
        # Update destination to Paris
        client.patch(f"/travel-plans/{pid_paris_over}", json={"destination": "Paris"})
        _add_expense(client, pid_paris_over, 500.0)

        pid_rome_over = _make_plan(client, budget=100.0)
        client.patch(f"/travel-plans/{pid_rome_over}", json={"destination": "Rome"})
        _add_expense(client, pid_rome_over, 500.0)

        resp = client.get("/travel-plans?over_budget=true&destination=Paris")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["items"]]
        assert pid_paris_over in ids
        assert pid_rome_over not in ids

    def test_response_is_paginated_envelope(self, client: TestClient):
        resp = client.get("/travel-plans?over_budget=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
