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


class TestChatPageStructure:
    """Task #42: Chat page HTML/CSS structure."""

    def test_chat_page_structure(self, client: TestClient):
        resp = client.get("/")
        content = resp.content.decode()

        # Nav link present
        assert "Chat" in content

        # Split-pane CSS classes defined
        assert "chat-layout" in content
        assert "chat-col" in content
        assert "dashboard-col" in content

        # Agent card CSS classes defined
        assert "agent-card" in content
        assert "agent-idle" in content
        assert "agent-thinking" in content
        assert "agent-working" in content
        assert "agent-done" in content
        assert "agent-error" in content

        # Animations defined
        assert "pulse" in content
        assert "@keyframes spin" in content

        # All 7 agent definitions present in JS
        assert "Coordinator" in content
        assert "Planner" in content
        assert "Place Scout" in content
        assert "Hotel Finder" in content
        assert "Flight Finder" in content
        assert "Budget Analyst" in content
        assert "Secretary" in content

        # Agent data-agent attributes present (for SSE handler)
        assert 'data-agent=' in content or "data-agent" in content


class TestChatJs:
    """Task #43: chat.js SSE client + message UI + agent_status handler."""

    def test_chat_js_served(self, client: TestClient):
        resp = client.get("/static/chat.js")
        assert resp.status_code == 200

    def test_chat_js_content_type(self, client: TestClient):
        resp = client.get("/static/chat.js")
        ct = resp.headers.get("content-type", "")
        assert "javascript" in ct or "text/" in ct

    def test_chat_js_has_init_chat_session(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "initChatSession" in content

    def test_chat_js_has_send_chat_message(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "sendChatMessage" in content

    def test_chat_js_has_sse_stream_reader(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "streamSseResponse" in content

    def test_chat_js_has_handle_sse_event(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "handleSseEvent" in content

    def test_chat_js_handles_agent_status_event(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "agent_status" in content

    def test_chat_js_handles_chat_chunk_event(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "chat_chunk" in content

    def test_chat_js_handles_chat_done_event(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "chat_done" in content

    def test_chat_js_handles_plan_update_event(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "plan_update" in content

    def test_chat_js_has_reset_agent_cards(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "resetAgentCards" in content

    def test_chat_js_has_append_ai_bubble(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "appendAiBubble" in content

    def test_chat_js_posts_to_chat_sessions(self, client: TestClient):
        content = client.get("/static/chat.js").text
        assert "/chat/sessions" in content

    def test_index_html_loads_chat_js(self, client: TestClient):
        content = client.get("/").text
        assert "chat.js" in content

    def test_index_html_calls_init_chat_session(self, client: TestClient):
        content = client.get("/").text
        assert "initChatSession" in content
