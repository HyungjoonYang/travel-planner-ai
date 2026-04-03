"""Tests for Google Calendar integration (task #11).

All Google Calendar API calls are mocked via unittest.mock — no real OAuth token needed.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import httpx

from app.calendar_service import CalendarService, CalendarExportResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_place(id=1, name="Senso-ji", category="sightseeing", ai_reason="Famous temple", order=0):
    p = SimpleNamespace(
        id=id, name=name, category=category, ai_reason=ai_reason, order=order,
        address="2-3-1 Asakusa, Tokyo", estimated_cost=0.0,
    )
    return p


def make_itinerary(id=1, day_date=None, notes="", transport="Walk", places=None):
    if day_date is None:
        day_date = date(2024, 3, 15)
    if places is None:
        places = [make_place()]
    return SimpleNamespace(
        id=id, date=day_date, notes=notes, transport=transport, places=places
    )


def make_plan(id=1, destination="Tokyo", itineraries=None):
    if itineraries is None:
        itineraries = [make_itinerary()]
    return SimpleNamespace(id=id, destination=destination, itineraries=itineraries)


FAKE_API_RESPONSE = {
    "id": "abc123",
    "htmlLink": "https://calendar.google.com/event?eid=abc123",
    "summary": "Tokyo — Mar 15",
}


# ---------------------------------------------------------------------------
# CalendarService._build_event_body
# ---------------------------------------------------------------------------

class TestBuildEventBody:
    def test_summary_contains_destination_and_date(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(day_date=date(2024, 3, 15))
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Tokyo" in body["summary"]
        assert "Mar 15" in body["summary"]

    def test_start_date_matches_itinerary(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(day_date=date(2024, 6, 1))
        body = svc._build_event_body(itinerary, "Paris")
        assert body["start"]["date"] == "2024-06-01"

    def test_end_date_is_next_day(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(day_date=date(2024, 6, 1))
        body = svc._build_event_body(itinerary, "Paris")
        assert body["end"]["date"] == "2024-06-02"

    def test_location_is_destination(self):
        svc = CalendarService("tok")
        body = svc._build_event_body(make_itinerary(), "Kyoto")
        assert body["location"] == "Kyoto"

    def test_description_includes_transport(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(transport="Subway")
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Subway" in body["description"]

    def test_description_includes_place_name(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(places=[make_place(name="Shibuya Crossing")])
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Shibuya Crossing" in body["description"]

    def test_description_includes_place_category(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(places=[make_place(category="food")])
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "food" in body["description"]

    def test_description_includes_ai_reason(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(places=[make_place(ai_reason="Best ramen in Tokyo")])
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Best ramen in Tokyo" in body["description"]

    def test_description_includes_notes(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(notes="Bring umbrella")
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Bring umbrella" in body["description"]

    def test_places_ordered_by_order_field(self):
        svc = CalendarService("tok")
        places = [
            make_place(id=2, name="B Place", order=1),
            make_place(id=1, name="A Place", order=0),
        ]
        itinerary = make_itinerary(places=places)
        body = svc._build_event_body(itinerary, "Tokyo")
        desc = body["description"]
        assert desc.index("A Place") < desc.index("B Place")

    def test_no_transport_section_when_empty(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(transport="")
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Transport:" not in body["description"]

    def test_no_notes_section_when_empty(self):
        svc = CalendarService("tok")
        itinerary = make_itinerary(notes="")
        body = svc._build_event_body(itinerary, "Tokyo")
        assert "Notes:" not in body["description"]

    def test_body_has_all_required_keys(self):
        svc = CalendarService("tok")
        body = svc._build_event_body(make_itinerary(), "Tokyo")
        for key in ("summary", "description", "start", "end", "location"):
            assert key in body

    def test_start_end_use_date_key_not_datetime(self):
        svc = CalendarService("tok")
        body = svc._build_event_body(make_itinerary(), "Tokyo")
        assert "date" in body["start"]
        assert "date" in body["end"]
        assert "dateTime" not in body["start"]


# ---------------------------------------------------------------------------
# CalendarService.create_event
# ---------------------------------------------------------------------------

class TestCreateEvent:
    def test_posts_to_correct_url(self):
        svc = CalendarService("my-token")
        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_API_RESPONSE
        mock_response.raise_for_status.return_value = None

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_client_instance
            mock_client_instance.post.return_value = mock_response

            svc.create_event({"summary": "Test"})

            call_args = mock_client_instance.post.call_args
            assert "calendar/v3/calendars/primary/events" in call_args[0][0]

    def test_sends_bearer_auth_header(self):
        svc = CalendarService("super-secret-token")
        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_API_RESPONSE
        mock_response.raise_for_status.return_value = None

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_client_instance
            mock_client_instance.post.return_value = mock_response

            svc.create_event({})

            headers = mock_client_instance.post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer super-secret-token"

    def test_returns_api_response_json(self):
        svc = CalendarService("tok")
        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_API_RESPONSE
        mock_response.raise_for_status.return_value = None

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_client_instance
            mock_client_instance.post.return_value = mock_response

            result = svc.create_event({"summary": "X"})

        assert result["id"] == "abc123"

    def test_raises_on_http_error(self):
        svc = CalendarService("bad-token")

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_client_instance
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            )
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                svc.create_event({})

    def test_sends_event_body_as_json(self):
        svc = CalendarService("tok")
        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_API_RESPONSE
        mock_response.raise_for_status.return_value = None

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_client_instance
            mock_client_instance.post.return_value = mock_response

            payload = {"summary": "Day 1", "start": {"date": "2024-03-15"}}
            svc.create_event(payload)

            call_kwargs = mock_client_instance.post.call_args[1]
            assert call_kwargs["json"] == payload


# ---------------------------------------------------------------------------
# CalendarService.export_plan
# ---------------------------------------------------------------------------

class TestExportPlan:
    def _mock_create_event(self, idx=0):
        return {
            "id": f"event-{idx}",
            "htmlLink": f"https://calendar.google.com/event?eid=event-{idx}",
        }

    def test_returns_export_result_type(self):
        plan = make_plan()
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value=self._mock_create_event()):
            result = svc.export_plan(plan)
        assert isinstance(result, CalendarExportResult)

    def test_events_created_count_matches_itineraries(self):
        plan = make_plan(itineraries=[make_itinerary(id=1), make_itinerary(id=2, day_date=date(2024, 3, 16))])
        svc = CalendarService("tok")
        call_count = [0]
        def side_effect(body):
            r = self._mock_create_event(call_count[0])
            call_count[0] += 1
            return r
        with patch.object(svc, "create_event", side_effect=side_effect):
            result = svc.export_plan(plan)
        assert result.events_created == 2

    def test_plan_id_in_result(self):
        plan = make_plan(id=42)
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value=self._mock_create_event()):
            result = svc.export_plan(plan)
        assert result.plan_id == 42

    def test_destination_in_result(self):
        plan = make_plan(destination="Osaka")
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value=self._mock_create_event()):
            result = svc.export_plan(plan)
        assert result.destination == "Osaka"

    def test_event_ids_mapped_correctly(self):
        plan = make_plan(itineraries=[make_itinerary(id=1)])
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value={"id": "xyz789", "htmlLink": "http://cal/xyz789"}):
            result = svc.export_plan(plan)
        assert result.events[0].event_id == "xyz789"

    def test_event_link_mapped_correctly(self):
        plan = make_plan(itineraries=[make_itinerary(id=1)])
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value={"id": "e1", "htmlLink": "http://calendar.google.com/e1"}):
            result = svc.export_plan(plan)
        assert result.events[0].event_link == "http://calendar.google.com/e1"

    def test_itineraries_sorted_by_date(self):
        it1 = make_itinerary(id=1, day_date=date(2024, 3, 17))
        it2 = make_itinerary(id=2, day_date=date(2024, 3, 15))
        plan = make_plan(itineraries=[it1, it2])
        svc = CalendarService("tok")
        call_dates = []
        def side_effect(body):
            call_dates.append(body["start"]["date"])
            return {"id": f"e{len(call_dates)}", "htmlLink": ""}
        with patch.object(svc, "create_event", side_effect=side_effect):
            svc.export_plan(plan)
        assert call_dates == ["2024-03-15", "2024-03-17"]

    def test_empty_itineraries_returns_zero_events(self):
        plan = make_plan(itineraries=[])
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value=self._mock_create_event()):
            result = svc.export_plan(plan)
        assert result.events_created == 0
        assert result.events == []

    def test_event_date_field_correct(self):
        plan = make_plan(itineraries=[make_itinerary(id=1, day_date=date(2024, 5, 20))])
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value={"id": "e1", "htmlLink": ""}):
            result = svc.export_plan(plan)
        assert result.events[0].event_date == date(2024, 5, 20)

    def test_day_itinerary_id_field_correct(self):
        plan = make_plan(itineraries=[make_itinerary(id=99)])
        svc = CalendarService("tok")
        with patch.object(svc, "create_event", return_value={"id": "e1", "htmlLink": ""}):
            result = svc.export_plan(plan)
        assert result.events[0].day_itinerary_id == 99

    def test_missing_html_link_defaults_to_empty_string(self):
        plan = make_plan(itineraries=[make_itinerary(id=1)])
        svc = CalendarService("tok")
        # API returns response without htmlLink
        with patch.object(svc, "create_event", return_value={"id": "e1"}):
            result = svc.export_plan(plan)
        assert result.events[0].event_link == ""


# ---------------------------------------------------------------------------
# Router endpoint: POST /plans/{plan_id}/calendar/export
# ---------------------------------------------------------------------------

class TestCalendarExportEndpoint:

    def _create_plan_with_itinerary(self, client):
        plan_resp = client.post("/plans/", json={
            "destination": "Tokyo",
            "start_date": "2024-03-15",
            "end_date": "2024-03-16",
            "budget": 2000.0,
            "interests": "culture",
        })
        assert plan_resp.status_code == 201
        plan_id = plan_resp.json()["id"]

        # Add a day itinerary via the AI generate mock OR directly via CRUD
        # Use CRUD endpoint to add itinerary+places
        return plan_id

    def test_404_when_plan_not_found(self, client):
        with patch("app.calendar_service.httpx.Client"):
            resp = client.post(
                "/plans/9999/calendar/export",
                json={"access_token": "fake-token"},
            )
        assert resp.status_code == 404

    def test_422_when_plan_has_no_itineraries(self, client):
        plan_resp = client.post("/travel-plans", json={
            "destination": "Tokyo",
            "start_date": "2024-03-15",
            "end_date": "2024-03-16",
            "budget": 2000.0,
        })
        plan_id = plan_resp.json()["id"]

        with patch("app.calendar_service.httpx.Client"):
            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "fake-token"},
            )
        assert resp.status_code == 422
        assert "no itinerary" in resp.json()["detail"].lower()

    def test_422_when_access_token_missing(self, client):
        plan_resp = client.post("/travel-plans", json={
            "destination": "Tokyo",
            "start_date": "2024-03-15",
            "end_date": "2024-03-16",
            "budget": 2000.0,
        })
        plan_id = plan_resp.json()["id"]

        resp = client.post(f"/plans/{plan_id}/calendar/export", json={})
        assert resp.status_code == 422

    def test_401_on_invalid_google_token(self, client):
        # Create plan with AI generate (mocked)
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(date="2024-03-15", places=[], notes="", transport="Walk")
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2024-03-15",
                "end_date": "2024-03-15",
                "budget": 1000.0,
            })
        assert gen_resp.status_code == 201
        plan_id = gen_resp.json()["id"]

        # Mock httpx to return 401
        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            )
            mock_inst.post.return_value = mock_resp

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "bad-token"},
            )

        assert resp.status_code == 401
        assert "access token" in resp.json()["detail"].lower()

    def test_502_on_google_api_server_error(self, client):
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(date="2024-03-15", places=[], notes="", transport="Walk")
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2024-03-15",
                "end_date": "2024-03-15",
                "budget": 1000.0,
            })
        plan_id = gen_resp.json()["id"]

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=MagicMock(),
                response=MagicMock(status_code=503),
            )
            mock_inst.post.return_value = mock_resp

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "tok"},
            )

        assert resp.status_code == 502

    def test_502_on_network_error(self, client):
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(date="2024-03-15", places=[], notes="", transport="Walk")
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2024-03-15",
                "end_date": "2024-03-15",
                "budget": 1000.0,
            })
        plan_id = gen_resp.json()["id"]

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_inst.post.side_effect = httpx.ConnectError("Connection refused")

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "tok"},
            )

        assert resp.status_code == 502

    def test_successful_export_returns_200(self, client):
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(
                    date="2024-03-15",
                    places=[AIPlace(name="Senso-ji", category="sightseeing", address="Asakusa", estimated_cost=0.0, ai_reason="Famous temple")],
                    notes="Great day",
                    transport="Subway",
                )
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2024-03-15",
                "end_date": "2024-03-15",
                "budget": 1000.0,
            })
        plan_id = gen_resp.json()["id"]

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "id": "cal-event-1",
                "htmlLink": "https://calendar.google.com/event?eid=cal-event-1",
            }
            mock_inst.post.return_value = mock_resp

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "valid-token"},
            )

        assert resp.status_code == 200

    def test_successful_export_response_structure(self, client):
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(date="2024-03-15", places=[], notes="", transport="Walk")
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Kyoto",
                "start_date": "2024-03-15",
                "end_date": "2024-03-15",
                "budget": 1500.0,
            })
        plan_id = gen_resp.json()["id"]

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"id": "ev1", "htmlLink": "http://cal/ev1"}
            mock_inst.post.return_value = mock_resp

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "tok"},
            )

        data = resp.json()
        assert "plan_id" in data
        assert "destination" in data
        assert "events_created" in data
        assert "events" in data
        assert data["destination"] == "Kyoto"

    def test_successful_export_events_count(self, client):
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(date="2024-03-15", places=[], notes="", transport="Walk"),
                AIDayItinerary(date="2024-03-16", places=[], notes="", transport="Bus"),
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2024-03-15",
                "end_date": "2024-03-16",
                "budget": 2000.0,
            })
        plan_id = gen_resp.json()["id"]

        call_count = [0]
        def make_response():
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            idx = call_count[0]
            call_count[0] += 1
            mock_resp.json.return_value = {"id": f"ev{idx}", "htmlLink": ""}
            return mock_resp

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_inst.post.side_effect = lambda *a, **kw: make_response()

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "tok"},
            )

        assert resp.json()["events_created"] == 2

    def test_successful_export_event_fields(self, client):
        with patch("app.ai.GeminiService.generate_itinerary") as mock_gen:
            from app.ai import AIItineraryResult, AIDayItinerary
            mock_gen.return_value = AIItineraryResult(days=[
                AIDayItinerary(date="2024-03-15", places=[], notes="", transport="Walk")
            ])
            gen_resp = client.post("/ai/generate", json={
                "destination": "Tokyo",
                "start_date": "2024-03-15",
                "end_date": "2024-03-15",
                "budget": 1000.0,
            })
        plan_id = gen_resp.json()["id"]

        with patch("app.calendar_service.httpx.Client") as MockClient:
            mock_inst = MagicMock()
            MockClient.return_value.__enter__.return_value = mock_inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"id": "event-id-99", "htmlLink": "http://cal/99"}
            mock_inst.post.return_value = mock_resp

            resp = client.post(
                f"/plans/{plan_id}/calendar/export",
                json={"access_token": "tok"},
            )

        event = resp.json()["events"][0]
        assert "day_itinerary_id" in event
        assert "event_date" in event
        assert "event_id" in event
        assert "event_link" in event
        assert event["event_id"] == "event-id-99"
