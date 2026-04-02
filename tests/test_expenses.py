"""Tests for expense tracking endpoints (Task #14)."""
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAN_PAYLOAD = {
    "destination": "Tokyo",
    "start_date": "2026-06-01",
    "end_date": "2026-06-07",
    "budget": 2000.0,
    "interests": "food,culture",
    "status": "draft",
}

EXPENSE_PAYLOAD = {
    "name": "Ramen dinner",
    "amount": 15.0,
    "category": "food",
    "date": "2026-06-02",
    "notes": "Ichiran Shinjuku",
}


def _create_plan(client):
    r = client.post("/travel-plans", json=PLAN_PAYLOAD)
    assert r.status_code == 201
    return r.json()["id"]


def _create_expense(client, plan_id, payload=None):
    data = payload or EXPENSE_PAYLOAD
    r = client.post(f"/plans/{plan_id}/expenses", json=data)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Schema / unit tests (no HTTP)
# ---------------------------------------------------------------------------


class TestExpenseSchemas:
    def test_expense_create_requires_name(self):
        from pydantic import ValidationError
        from app.schemas import ExpenseCreate

        with pytest.raises(ValidationError):
            ExpenseCreate(amount=10.0)

    def test_expense_create_requires_positive_amount(self):
        from pydantic import ValidationError
        from app.schemas import ExpenseCreate

        with pytest.raises(ValidationError):
            ExpenseCreate(name="test", amount=0.0)

    def test_expense_create_amount_must_be_gt_zero(self):
        from pydantic import ValidationError
        from app.schemas import ExpenseCreate

        with pytest.raises(ValidationError):
            ExpenseCreate(name="test", amount=-5.0)

    def test_expense_create_valid(self):
        from app.schemas import ExpenseCreate

        e = ExpenseCreate(name="taxi", amount=12.50, category="transport")
        assert e.name == "taxi"
        assert e.amount == 12.50
        assert e.category == "transport"

    def test_expense_create_defaults(self):
        from app.schemas import ExpenseCreate

        e = ExpenseCreate(name="snack", amount=3.0)
        assert e.category == ""
        assert e.date is None
        assert e.notes == ""

    def test_expense_update_all_optional(self):
        from app.schemas import ExpenseUpdate

        u = ExpenseUpdate()
        assert u.name is None
        assert u.amount is None

    def test_expense_update_rejects_zero_amount(self):
        from pydantic import ValidationError
        from app.schemas import ExpenseUpdate

        with pytest.raises(ValidationError):
            ExpenseUpdate(amount=0.0)

    def test_budget_summary_fields(self):
        from app.schemas import BudgetSummary

        s = BudgetSummary(
            plan_id=1,
            budget=1000.0,
            total_spent=250.0,
            remaining=750.0,
            by_category={"food": 100.0, "transport": 150.0},
            expense_count=2,
            over_budget=False,
            overage_pct=0.0,
        )
        assert s.remaining == 750.0
        assert s.by_category["food"] == 100.0

    def test_expense_name_max_length(self):
        from pydantic import ValidationError
        from app.schemas import ExpenseCreate

        with pytest.raises(ValidationError):
            ExpenseCreate(name="x" * 256, amount=1.0)

    def test_expense_name_min_length(self):
        from pydantic import ValidationError
        from app.schemas import ExpenseCreate

        with pytest.raises(ValidationError):
            ExpenseCreate(name="", amount=1.0)


# ---------------------------------------------------------------------------
# POST /plans/{plan_id}/expenses
# ---------------------------------------------------------------------------


class TestCreateExpense:
    def test_returns_201(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/expenses", json=EXPENSE_PAYLOAD)
        assert r.status_code == 201

    def test_response_has_id(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/expenses", json=EXPENSE_PAYLOAD)
        assert "id" in r.json()

    def test_response_travel_plan_id(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/expenses", json=EXPENSE_PAYLOAD)
        assert r.json()["travel_plan_id"] == plan_id

    def test_response_fields(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/expenses", json=EXPENSE_PAYLOAD)
        body = r.json()
        assert body["name"] == "Ramen dinner"
        assert body["amount"] == 15.0
        assert body["category"] == "food"

    def test_404_for_unknown_plan(self, client):
        r = client.post("/plans/9999/expenses", json=EXPENSE_PAYLOAD)
        assert r.status_code == 404

    def test_422_missing_name(self, client):
        plan_id = _create_plan(client)
        r = client.post(f"/plans/{plan_id}/expenses", json={"amount": 10.0})
        assert r.status_code == 422

    def test_422_zero_amount(self, client):
        plan_id = _create_plan(client)
        r = client.post(
            f"/plans/{plan_id}/expenses", json={"name": "test", "amount": 0.0}
        )
        assert r.status_code == 422

    def test_optional_date_null(self, client):
        plan_id = _create_plan(client)
        payload = {"name": "souvenir", "amount": 5.0}
        r = client.post(f"/plans/{plan_id}/expenses", json=payload)
        assert r.status_code == 201
        assert r.json()["date"] is None

    def test_multiple_expenses_same_plan(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id)
        _create_expense(client, plan_id, {"name": "taxi", "amount": 8.0})
        r = client.get(f"/plans/{plan_id}/expenses")
        assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# GET /plans/{plan_id}/expenses
# ---------------------------------------------------------------------------


class TestListExpenses:
    def test_returns_empty_list(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/expenses")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_created_expenses(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id)
        r = client.get(f"/plans/{plan_id}/expenses")
        assert len(r.json()) == 1

    def test_404_for_unknown_plan(self, client):
        r = client.get("/plans/9999/expenses")
        assert r.status_code == 404

    def test_scoped_to_plan(self, client):
        plan_a = _create_plan(client)
        plan_b = _create_plan(client)
        _create_expense(client, plan_a)
        r = client.get(f"/plans/{plan_b}/expenses")
        assert r.json() == []

    def test_ordered_by_id(self, client):
        plan_id = _create_plan(client)
        e1 = _create_expense(client, plan_id, {"name": "first", "amount": 1.0})
        e2 = _create_expense(client, plan_id, {"name": "second", "amount": 2.0})
        ids = [e["id"] for e in client.get(f"/plans/{plan_id}/expenses").json()]
        assert ids == [e1["id"], e2["id"]]


# ---------------------------------------------------------------------------
# GET /plans/{plan_id}/expenses/summary
# ---------------------------------------------------------------------------


class TestBudgetSummary:
    def test_returns_200(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/expenses/summary")
        assert r.status_code == 200

    def test_empty_summary(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/expenses/summary")
        body = r.json()
        assert body["total_spent"] == 0.0
        assert body["remaining"] == 2000.0
        assert body["expense_count"] == 0
        assert body["by_category"] == {}

    def test_budget_matches_plan(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/expenses/summary")
        assert r.json()["budget"] == 2000.0

    def test_total_spent_after_expenses(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id, {"name": "ramen", "amount": 15.0, "category": "food"})
        _create_expense(client, plan_id, {"name": "taxi", "amount": 20.0, "category": "transport"})
        r = client.get(f"/plans/{plan_id}/expenses/summary")
        assert r.json()["total_spent"] == 35.0

    def test_remaining_decreases(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id, {"name": "dinner", "amount": 50.0})
        r = client.get(f"/plans/{plan_id}/expenses/summary")
        assert r.json()["remaining"] == 1950.0

    def test_by_category_breakdown(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id, {"name": "ramen", "amount": 15.0, "category": "food"})
        _create_expense(client, plan_id, {"name": "sushi", "amount": 30.0, "category": "food"})
        _create_expense(client, plan_id, {"name": "train", "amount": 10.0, "category": "transport"})
        body = client.get(f"/plans/{plan_id}/expenses/summary").json()
        assert body["by_category"]["food"] == 45.0
        assert body["by_category"]["transport"] == 10.0

    def test_expense_count(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id)
        _create_expense(client, plan_id, {"name": "train", "amount": 5.0})
        body = client.get(f"/plans/{plan_id}/expenses/summary").json()
        assert body["expense_count"] == 2

    def test_404_for_unknown_plan(self, client):
        r = client.get("/plans/9999/expenses/summary")
        assert r.status_code == 404

    def test_plan_id_in_summary(self, client):
        plan_id = _create_plan(client)
        body = client.get(f"/plans/{plan_id}/expenses/summary").json()
        assert body["plan_id"] == plan_id

    def test_no_category_falls_back_to_other(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id, {"name": "misc", "amount": 7.0})
        body = client.get(f"/plans/{plan_id}/expenses/summary").json()
        # category defaults to "" → bucketed as "other"
        assert "other" in body["by_category"]


# ---------------------------------------------------------------------------
# GET /plans/{plan_id}/expenses/{expense_id}
# ---------------------------------------------------------------------------


class TestGetExpense:
    def test_returns_200(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.get(f"/plans/{plan_id}/expenses/{expense['id']}")
        assert r.status_code == 200

    def test_returns_correct_data(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.get(f"/plans/{plan_id}/expenses/{expense['id']}")
        assert r.json()["name"] == "Ramen dinner"

    def test_404_unknown_expense(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/plans/{plan_id}/expenses/9999")
        assert r.status_code == 404

    def test_404_expense_from_other_plan(self, client):
        plan_a = _create_plan(client)
        plan_b = _create_plan(client)
        expense = _create_expense(client, plan_a)
        r = client.get(f"/plans/{plan_b}/expenses/{expense['id']}")
        assert r.status_code == 404

    def test_404_unknown_plan(self, client):
        r = client.get("/plans/9999/expenses/1")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /plans/{plan_id}/expenses/{expense_id}
# ---------------------------------------------------------------------------


class TestUpdateExpense:
    def test_returns_200(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.patch(f"/plans/{plan_id}/expenses/{expense['id']}", json={"amount": 20.0})
        assert r.status_code == 200

    def test_updates_amount(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.patch(f"/plans/{plan_id}/expenses/{expense['id']}", json={"amount": 99.0})
        assert r.json()["amount"] == 99.0

    def test_updates_name(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.patch(
            f"/plans/{plan_id}/expenses/{expense['id']}", json={"name": "Tonkotsu ramen"}
        )
        assert r.json()["name"] == "Tonkotsu ramen"

    def test_updates_category(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.patch(
            f"/plans/{plan_id}/expenses/{expense['id']}", json={"category": "activity"}
        )
        assert r.json()["category"] == "activity"

    def test_partial_update_preserves_other_fields(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.patch(f"/plans/{plan_id}/expenses/{expense['id']}", json={"amount": 25.0})
        body = r.json()
        assert body["name"] == "Ramen dinner"
        assert body["category"] == "food"

    def test_422_zero_amount(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.patch(f"/plans/{plan_id}/expenses/{expense['id']}", json={"amount": 0.0})
        assert r.status_code == 422

    def test_404_unknown_expense(self, client):
        plan_id = _create_plan(client)
        r = client.patch(f"/plans/{plan_id}/expenses/9999", json={"amount": 10.0})
        assert r.status_code == 404

    def test_404_unknown_plan(self, client):
        r = client.patch("/plans/9999/expenses/1", json={"amount": 10.0})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /plans/{plan_id}/expenses/{expense_id}
# ---------------------------------------------------------------------------


class TestDeleteExpense:
    def test_returns_204(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        r = client.delete(f"/plans/{plan_id}/expenses/{expense['id']}")
        assert r.status_code == 204

    def test_expense_gone_after_delete(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        client.delete(f"/plans/{plan_id}/expenses/{expense['id']}")
        r = client.get(f"/plans/{plan_id}/expenses/{expense['id']}")
        assert r.status_code == 404

    def test_list_empty_after_delete(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        client.delete(f"/plans/{plan_id}/expenses/{expense['id']}")
        assert client.get(f"/plans/{plan_id}/expenses").json() == []

    def test_summary_updates_after_delete(self, client):
        plan_id = _create_plan(client)
        expense = _create_expense(client, plan_id)
        client.delete(f"/plans/{plan_id}/expenses/{expense['id']}")
        body = client.get(f"/plans/{plan_id}/expenses/summary").json()
        assert body["total_spent"] == 0.0
        assert body["expense_count"] == 0

    def test_404_unknown_expense(self, client):
        plan_id = _create_plan(client)
        r = client.delete(f"/plans/{plan_id}/expenses/9999")
        assert r.status_code == 404

    def test_404_unknown_plan(self, client):
        r = client.delete("/plans/9999/expenses/1")
        assert r.status_code == 404

    def test_deleting_plan_cascades_to_expenses(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id)
        client.delete(f"/travel-plans/{plan_id}")
        # Plan is gone; expenses are gone via cascade
        r = client.get(f"/plans/{plan_id}/expenses")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Integration: expense tracking visible in TravelPlanOut
# ---------------------------------------------------------------------------


class TestExpensesInTravelPlan:
    def test_plan_includes_expenses(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id)
        r = client.get(f"/travel-plans/{plan_id}")
        assert len(r.json()["expenses"]) == 1

    def test_plan_expense_fields(self, client):
        plan_id = _create_plan(client)
        _create_expense(client, plan_id)
        expense = client.get(f"/travel-plans/{plan_id}").json()["expenses"][0]
        assert expense["name"] == "Ramen dinner"
        assert expense["amount"] == 15.0

    def test_plan_has_no_expenses_initially(self, client):
        plan_id = _create_plan(client)
        r = client.get(f"/travel-plans/{plan_id}")
        assert r.json()["expenses"] == []
