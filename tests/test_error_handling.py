"""Tests for comprehensive error handling and validation (task #17)."""
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app.main import app
from app.schemas import TravelPlanCreate, TravelPlanUpdate

client = TestClient(app)


# ---------------------------------------------------------------------------
# Schema cross-field validation: end_date >= start_date
# ---------------------------------------------------------------------------

class TestTravelPlanDateValidation:
    def test_create_valid_same_day(self):
        plan = TravelPlanCreate(
            destination="Tokyo",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            budget=1000.0,
        )
        assert plan.start_date == plan.end_date

    def test_create_valid_multi_day(self):
        plan = TravelPlanCreate(
            destination="Paris",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            budget=2000.0,
        )
        assert plan.end_date > plan.start_date

    def test_create_invalid_end_before_start(self):
        with pytest.raises(ValidationError) as exc_info:
            TravelPlanCreate(
                destination="Tokyo",
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 5),
                budget=1000.0,
            )
        errors = exc_info.value.errors()
        assert any("end_date" in str(e) or "start_date" in str(e) for e in errors)

    def test_update_invalid_end_before_start(self):
        with pytest.raises(ValidationError):
            TravelPlanUpdate(
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 5),
            )

    def test_update_only_start_date_no_error(self):
        # Partial update with only start_date should not raise
        update = TravelPlanUpdate(start_date=date(2026, 6, 1))
        assert update.start_date == date(2026, 6, 1)

    def test_update_only_end_date_no_error(self):
        update = TravelPlanUpdate(end_date=date(2026, 6, 10))
        assert update.end_date == date(2026, 6, 10)

    def test_update_valid_dates(self):
        update = TravelPlanUpdate(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
        )
        assert update.end_date >= update.start_date


# ---------------------------------------------------------------------------
# API: 422 response for invalid date range via POST /travel-plans
# ---------------------------------------------------------------------------

class TestTravelPlanAPIDateValidation:
    def test_post_invalid_date_range_returns_422(self):
        resp = client.post("/travel-plans", json={
            "destination": "Seoul",
            "start_date": "2026-06-10",
            "end_date": "2026-06-05",
            "budget": 500,
        })
        assert resp.status_code == 422

    def test_post_valid_date_range_returns_201(self):
        resp = client.post("/travel-plans", json={
            "destination": "Seoul",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "budget": 500,
        })
        assert resp.status_code == 201

    def test_patch_invalid_date_range_returns_422(self):
        # Create a plan first
        create_resp = client.post("/travel-plans", json={
            "destination": "Berlin",
            "start_date": "2026-07-01",
            "end_date": "2026-07-05",
            "budget": 800,
        })
        assert create_resp.status_code == 201
        plan_id = create_resp.json()["id"]

        resp = client.patch(f"/travel-plans/{plan_id}", json={
            "start_date": "2026-07-10",
            "end_date": "2026-07-03",
        })
        assert resp.status_code == 422

    def test_post_zero_budget_returns_422(self):
        resp = client.post("/travel-plans", json={
            "destination": "Rome",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "budget": 0,
        })
        assert resp.status_code == 422

    def test_post_negative_budget_returns_422(self):
        resp = client.post("/travel-plans", json={
            "destination": "Rome",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "budget": -100,
        })
        assert resp.status_code == 422

    def test_post_invalid_status_returns_422(self):
        resp = client.post("/travel-plans", json={
            "destination": "Rome",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "budget": 500,
            "status": "cancelled",
        })
        assert resp.status_code == 422

    def test_post_empty_destination_returns_422(self):
        resp = client.post("/travel-plans", json={
            "destination": "",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "budget": 500,
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------

class TestRequestIDMiddleware:
    def test_response_has_x_request_id_header(self):
        resp = client.get("/health")
        assert "x-request-id" in resp.headers

    def test_custom_request_id_is_echoed(self):
        resp = client.get("/health", headers={"X-Request-ID": "test-abc-123"})
        assert resp.headers.get("x-request-id") == "test-abc-123"

    def test_auto_generated_request_id_is_uuid(self):
        resp = client.get("/health")
        rid = resp.headers.get("x-request-id")
        assert rid is not None
        # UUID format: 8-4-4-4-12 hex chars
        import re
        assert re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", rid)

    def test_request_id_on_404(self):
        resp = client.get("/travel-plans/999999")
        assert "x-request-id" in resp.headers

    def test_request_id_on_201(self):
        resp = client.post("/travel-plans", json={
            "destination": "Sydney",
            "start_date": "2026-08-01",
            "end_date": "2026-08-05",
            "budget": 1500,
        })
        assert resp.status_code == 201
        assert "x-request-id" in resp.headers

    def test_request_id_on_422(self):
        resp = client.post("/travel-plans", json={
            "destination": "X",
            "start_date": "2026-06-10",
            "end_date": "2026-06-05",
            "budget": 100,
        })
        assert resp.status_code == 422
        assert "x-request-id" in resp.headers


# ---------------------------------------------------------------------------
# Expense validation
# ---------------------------------------------------------------------------

class TestExpenseValidation:
    def _make_plan(self):
        resp = client.post("/travel-plans", json={
            "destination": "Madrid",
            "start_date": "2026-09-01",
            "end_date": "2026-09-05",
            "budget": 1000,
        })
        return resp.json()["id"]

    def test_zero_amount_returns_422(self):
        plan_id = self._make_plan()
        resp = client.post(f"/plans/{plan_id}/expenses", json={
            "name": "Dinner",
            "amount": 0,
        })
        assert resp.status_code == 422

    def test_negative_amount_returns_422(self):
        plan_id = self._make_plan()
        resp = client.post(f"/plans/{plan_id}/expenses", json={
            "name": "Dinner",
            "amount": -50,
        })
        assert resp.status_code == 422

    def test_empty_name_returns_422(self):
        plan_id = self._make_plan()
        resp = client.post(f"/plans/{plan_id}/expenses", json={
            "name": "",
            "amount": 50,
        })
        assert resp.status_code == 422

    def test_valid_expense_accepted(self):
        plan_id = self._make_plan()
        resp = client.post(f"/plans/{plan_id}/expenses", json={
            "name": "Lunch",
            "amount": 25.5,
        })
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Global SQLAlchemy exception handlers (main.py)
# Use app.dependency_overrides to inject a get_db that raises the target
# exception, and raise_server_exceptions=False so FastAPI's exception handlers
# run instead of re-raising inside the test process.
# ---------------------------------------------------------------------------

from app.database import get_db as _get_db


def _db_that_raises(exc: Exception):
    """Return a generator dependency that raises *exc* before yielding."""
    def _override():
        raise exc
        yield  # noqa: unreachable — makes this a generator function
    return _override


class TestIntegrityErrorHandler:
    """IntegrityError → 409 Conflict"""

    def test_returns_409(self):
        exc = IntegrityError("duplicate key", params=None, orig=None)
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert resp.status_code == 409

    def test_response_detail(self):
        exc = IntegrityError("duplicate key", params=None, orig=None)
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "conflict" in resp.json()["detail"].lower()

    def test_response_has_request_id(self):
        exc = IntegrityError("duplicate key", params=None, orig=None)
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "x-request-id" in resp.headers


class TestOperationalErrorHandler:
    """OperationalError → 503 Service Unavailable"""

    def test_returns_503(self):
        exc = OperationalError("db unavailable", params=None, orig=None)
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert resp.status_code == 503

    def test_response_detail(self):
        exc = OperationalError("db unavailable", params=None, orig=None)
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "unavailable" in resp.json()["detail"].lower()

    def test_response_has_request_id(self):
        exc = OperationalError("db unavailable", params=None, orig=None)
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "x-request-id" in resp.headers


class TestSQLAlchemyErrorHandler:
    """Generic SQLAlchemyError → 500"""

    def test_returns_500(self):
        exc = SQLAlchemyError("unexpected db error")
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert resp.status_code == 500

    def test_response_detail(self):
        exc = SQLAlchemyError("unexpected db error")
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "database error" in resp.json()["detail"].lower()

    def test_response_has_request_id(self):
        exc = SQLAlchemyError("unexpected db error")
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "x-request-id" in resp.headers


class TestUnhandledExceptionHandler:
    """Unexpected Python Exception → 500"""

    def test_returns_500(self):
        exc = RuntimeError("unexpected boom")
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert resp.status_code == 500

    def test_response_detail(self):
        exc = RuntimeError("unexpected boom")
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "unexpected error" in resp.json()["detail"].lower()

    def test_response_has_request_id(self):
        exc = RuntimeError("unexpected boom")
        app.dependency_overrides[_get_db] = _db_that_raises(exc)
        try:
            resp = TestClient(app, raise_server_exceptions=False).get("/travel-plans")
        finally:
            app.dependency_overrides.pop(_get_db, None)
        assert "x-request-id" in resp.headers

    def test_reraises_http_exception(self):
        """The guard clause (line 86) re-raises FastAPIHTTPException untouched."""
        import asyncio
        from unittest.mock import MagicMock
        from fastapi.exceptions import HTTPException as FastAPIHTTPException
        from app.main import unhandled_exception_handler

        request = MagicMock()
        request.state.request_id = "test-req-id"
        http_exc = FastAPIHTTPException(status_code=404, detail="not found")

        async def _call():
            return await unhandled_exception_handler(request, http_exc)

        with pytest.raises(FastAPIHTTPException) as exc_info:
            asyncio.run(_call())
        assert exc_info.value.status_code == 404
