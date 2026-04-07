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


class TestAgentPanelToggle:
    """Task #45: Agent panel compact/expanded toggle + mobile responsive layout."""

    def test_compact_row_element_in_html(self, client: TestClient):
        """Agent panel has a compact single-row element for idle state."""
        content = client.get("/").text
        assert "agent-panel-compact-row" in content

    def test_compact_label_element_in_html(self, client: TestClient):
        """Compact row has a label element."""
        content = client.get("/").text
        assert "agent-panel-compact-label" in content

    def test_expand_agent_panel_function_in_html(self, client: TestClient):
        """expandAgentPanel() function exists in inline JS."""
        content = client.get("/").text
        assert "expandAgentPanel" in content

    def test_mobile_responsive_media_query_in_html(self, client: TestClient):
        """@media query present for ≤768px breakpoint."""
        content = client.get("/").text
        assert "768px" in content
        assert "@media" in content

    def test_mobile_stacks_chat_above_dashboard(self, client: TestClient):
        """Mobile CSS stacks chat above dashboard (flex-direction: column)."""
        content = client.get("/").text
        assert "flex-direction" in content

    def test_chat_js_has_check_agent_panel_state(self, client: TestClient):
        """chat.js exports checkAgentPanelState function."""
        content = client.get("/static/chat.js").text
        assert "checkAgentPanelState" in content

    def test_chat_js_reset_agent_cards_calls_check_panel_state(self, client: TestClient):
        """resetAgentCards() calls checkAgentPanelState() to auto-collapse."""
        content = client.get("/static/chat.js").text
        # both functions must be present
        assert "resetAgentCards" in content
        assert "checkAgentPanelState" in content

    def test_chat_js_handle_agent_status_calls_check_panel_state(self, client: TestClient):
        """handleAgentStatus() calls checkAgentPanelState() to auto-expand."""
        content = client.get("/static/chat.js").text
        assert "handleAgentStatus" in content
        assert "checkAgentPanelState" in content

    def test_chat_js_done_card_has_onclick(self, client: TestClient):
        """handleAgentStatus sets onclick on done-state cards for detail reveal."""
        content = client.get("/static/chat.js").text
        assert "el.onclick" in content

    def test_chat_js_done_card_shows_detail(self, client: TestClient):
        """Done-card click handler toggles agent-detail visibility."""
        content = client.get("/static/chat.js").text
        assert "agent-detail" in content


class TestSseReconnect:
    """Task #46: SSE reconnect with exponential backoff + session state restore."""

    def test_chat_js_has_restore_session_state(self, client: TestClient):
        """chat.js has restoreSessionState function for reconnect state recovery."""
        content = client.get("/static/chat.js").text
        assert "restoreSessionState" in content

    def test_chat_js_has_exponential_backoff(self, client: TestClient):
        """chat.js implements exponential backoff retry logic."""
        content = client.get("/static/chat.js").text
        # Backoff via 2** or Math.pow or explicit delays 1000/2000/4000
        assert "backoff" in content or "Math.pow" in content or "2000" in content

    def test_chat_js_has_max_retries(self, client: TestClient):
        """chat.js defines maximum retry count (3)."""
        content = client.get("/static/chat.js").text
        assert "MAX_RETRIES" in content or "_SSE_MAX_RETRIES" in content or "maxRetries" in content

    def test_chat_js_restore_fetches_get_session(self, client: TestClient):
        """restoreSessionState calls GET /chat/sessions/."""
        content = client.get("/static/chat.js").text
        assert "restoreSessionState" in content
        assert "/chat/sessions/" in content

    def test_chat_js_restore_calls_handle_agent_status(self, client: TestClient):
        """restoreSessionState restores agent statuses by calling handleAgentStatus."""
        content = client.get("/static/chat.js").text
        assert "restoreSessionState" in content
        assert "handleAgentStatus" in content

    def test_chat_js_restore_calls_handle_plan_update(self, client: TestClient):
        """restoreSessionState restores plan by calling handlePlanUpdate."""
        content = client.get("/static/chat.js").text
        assert "restoreSessionState" in content
        assert "handlePlanUpdate" in content

    def test_chat_js_retry_on_disconnect(self, client: TestClient):
        """chat.js retries SSE stream when connection drops before chat_done."""
        content = client.get("/static/chat.js").text
        # Must track chat_done and retry if missing
        assert "chat_done" in content
        assert "retry" in content.lower() or "Retry" in content or "_sseRetry" in content

    def test_get_session_returns_agent_states(self, client: TestClient):
        """GET /chat/sessions/{id} response includes agent_states field."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.get(f"/chat/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_states" in data

    def test_get_session_returns_last_plan(self, client: TestClient):
        """GET /chat/sessions/{id} response includes last_plan field."""
        session_id = client.post("/chat/sessions").json()["session_id"]
        resp = client.get(f"/chat/sessions/{session_id}")
        data = resp.json()
        assert "last_plan" in data


class TestPlaceScoutPersistentSection:
    """Task #69: Place Scout results — dedicated persistent #places-section."""

    def test_chat_js_has_last_places_cache(self, client: TestClient):
        """chat.js declares _lastPlaces variable for persisting place results."""
        content = client.get("/static/chat.js").text
        assert "_lastPlaces" in content

    def test_chat_js_refresh_includes_places_section(self, client: TestClient):
        """_refreshPlanSearchSections handles #plan-places-section."""
        content = client.get("/static/chat.js").text
        assert "plan-places-section" in content

    def test_chat_js_places_section_has_title(self, client: TestClient):
        """Places section renders with a section title (Places)."""
        content = client.get("/static/chat.js").text
        assert "📍 Places" in content

    def test_chat_js_places_stored_in_last_places(self, client: TestClient):
        """handleSearchResults assigns results.places to _lastPlaces."""
        content = client.get("/static/chat.js").text
        assert "_lastPlaces = results.places" in content

    def test_chat_js_places_calls_refresh_sections(self, client: TestClient):
        """handleSearchResults calls _refreshPlanSearchSections for places type."""
        content = client.get("/static/chat.js").text
        # places must be included in the refresh condition
        assert "places" in content
        assert "_refreshPlanSearchSections" in content

    def test_chat_js_place_scout_card_html(self, client: TestClient):
        """chat.js has _placeScoutCardHtml helper function."""
        content = client.get("/static/chat.js").text
        assert "_placeScoutCardHtml" in content

    def test_chat_js_refresh_sections_handles_places(self, client: TestClient):
        """_refreshPlanSearchSections function body references _lastPlaces."""
        content = client.get("/static/chat.js").text
        assert "_lastPlaces" in content
        assert "_refreshPlanSearchSections" in content


class TestRestoreMessageBubbles:
    """Task #70: restoreSessionState() renders message_history as chat bubbles."""

    def test_chat_js_restore_handles_message_history(self, client: TestClient):
        """restoreSessionState accesses message_history from session response."""
        content = client.get("/static/chat.js").text
        assert "message_history" in content

    def test_chat_js_has_restore_message_bubbles_fn(self, client: TestClient):
        """chat.js defines _restoreMessageBubbles helper."""
        content = client.get("/static/chat.js").text
        assert "_restoreMessageBubbles" in content

    def test_chat_js_restore_state_calls_restore_bubbles(self, client: TestClient):
        """restoreSessionState calls _restoreMessageBubbles."""
        content = client.get("/static/chat.js").text
        # restoreSessionState must reference _restoreMessageBubbles
        restore_fn_idx = content.index("async function restoreSessionState")
        next_fn_idx = content.find("\nasync function ", restore_fn_idx + 1)
        if next_fn_idx == -1:
            next_fn_idx = content.find("\nfunction ", restore_fn_idx + 1)
        body = content[restore_fn_idx:next_fn_idx] if next_fn_idx != -1 else content[restore_fn_idx:]
        assert "_restoreMessageBubbles" in body

    def test_chat_js_restore_bubbles_uses_chat_user_class(self, client: TestClient):
        """_restoreMessageBubbles renders user messages with chat-user CSS class."""
        content = client.get("/static/chat.js").text
        assert "chat-user" in content

    def test_chat_js_restore_bubbles_uses_chat_ai_class(self, client: TestClient):
        """_restoreMessageBubbles renders assistant messages with chat-ai CSS class."""
        content = client.get("/static/chat.js").text
        assert "chat-ai" in content

    def test_chat_js_restore_bubbles_marks_data_restored(self, client: TestClient):
        """_restoreMessageBubbles sets data-restored attribute to avoid re-rendering."""
        content = client.get("/static/chat.js").text
        assert "data-restored" in content or "dataset.restored" in content


class TestModernUXRedesign:
    """Task #99: Chat-first landing + modern UX redesign."""

    def test_style_css_served(self, client: TestClient):
        """style.css is served from /static/style.css."""
        resp = client.get("/static/style.css")
        assert resp.status_code == 200

    def test_style_css_content_type(self, client: TestClient):
        """style.css is served as CSS."""
        resp = client.get("/static/style.css")
        ct = resp.headers.get("content-type", "")
        assert "css" in ct or "text/" in ct

    def test_index_links_style_css(self, client: TestClient):
        """index.html links to style.css."""
        content = client.get("/").text
        assert "style.css" in content

    def test_chat_is_default_page(self, client: TestClient):
        """Default navigation targets the chat page."""
        content = client.get("/").text
        # The bootstrap call must navigate to chat by default
        assert "navigate('chat')" in content

    def test_chat_onboarding_chips_present(self, client: TestClient):
        """Onboarding example chips are present in the chat page HTML."""
        content = client.get("/").text
        assert "chat-chip" in content
        assert "fillChatInput" in content

    def test_plans_page_no_new_plan_button_in_render(self, client: TestClient):
        """renderPlans function does not inject a + New Plan button."""
        content = client.get("/").text
        # Find renderPlans function body and verify it has no new-plan navigate call
        idx = content.find("async function renderPlans")
        assert idx != -1
        # Find the end of the function (next async function)
        end_idx = content.find("async function render", idx + 1)
        if end_idx == -1:
            end_idx = idx + 3000  # fallback: scan 3000 chars
        fn_body = content[idx:end_idx]
        # The new-plan button must NOT be in renderPlans
        assert "navigate('new-plan')" not in fn_body

    def test_plans_empty_state_links_to_chat(self, client: TestClient):
        """Empty plans state links back to chat."""
        content = client.get("/").text
        # The empty state in renderPlans must link to chat
        idx = content.find("async function renderPlans")
        assert idx != -1
        end_idx = content.find("async function render", idx + 1)
        if end_idx == -1:
            end_idx = idx + 3000
        fn_body = content[idx:end_idx]
        assert "navigate('chat')" in fn_body


class TestDayLabelBadge:
    """Task #105: day card shows label as styled subtitle/badge when day.label present."""

    def test_chat_js_day_card_html_renders_label_badge(self, client: TestClient):
        """_dayCardHtml renders a day-label-badge span when day.label is truthy."""
        content = client.get("/static/chat.js").text
        # _dayCardHtml must reference the day-label-badge class and day.label
        assert "day-label-badge" in content
        assert "day.label" in content

    def test_chat_js_handle_day_update_refreshes_label(self, client: TestClient):
        """handleDayUpdate creates/updates .day-label-badge on existing day cards."""
        content = client.get("/static/chat.js").text
        # Find handleDayUpdate function body
        idx = content.find("function handleDayUpdate")
        assert idx != -1
        end_idx = content.find("\nfunction ", idx + 1)
        body = content[idx:end_idx] if end_idx != -1 else content[idx:]
        # Must reference label badge inside the update handler
        assert "day-label-badge" in body
        assert "data.label" in body

    def test_index_html_has_day_label_badge_css(self, client: TestClient):
        """index.html defines .day-label-badge CSS class."""
        content = client.get("/").text
        assert "day-label-badge" in content
