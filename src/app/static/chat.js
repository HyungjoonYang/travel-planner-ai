// chat.js — SSE client + chat message UI + agent_status event handler
// Loaded by index.html after the inline script block.
// Overrides the stub sendChatMessage defined in index.html.

'use strict';

let chatSessionId = null;
let currentStreamBubble = null;

// ---------------------------------------------------------------------------
// Timestamp helpers
// ---------------------------------------------------------------------------

/** Returns a Korean relative-time string for the given ISO timestamp. */
function formatRelativeTime(ts) {
  if (!ts) return '';
  const t = ts instanceof Date ? ts.getTime() : new Date(ts).getTime();
  if (isNaN(t)) return '';
  const diffMs = Date.now() - t;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '방금';
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}시간 전`;
  return `${Math.floor(diffHr / 24)}일 전`;
}

/** Refresh all visible .chat-timestamp spans with current relative times. */
function _updateAllTimestamps() {
  document.querySelectorAll('.chat-bubble[data-ts]').forEach(bubble => {
    const tsEl = bubble.querySelector('.chat-timestamp');
    if (tsEl) tsEl.textContent = formatRelativeTime(bubble.dataset.ts);
  });
}

/** Set the visible text of a bubble (targeting .chat-text if present). */
function _setBubbleText(bubble, text) {
  const textEl = bubble && bubble.querySelector('.chat-text');
  if (textEl) textEl.textContent = text;
  else if (bubble) bubble.textContent = text;
}

/** Append text to a bubble's .chat-text span (for streaming). */
function _appendBubbleText(bubble, text) {
  const textEl = bubble && bubble.querySelector('.chat-text');
  if (textEl) textEl.textContent += text;
  else if (bubble) bubble.textContent += text;
}

/** Create a chat bubble div with a text span and a timestamp span.
 *  @param {string} role  'user' | 'ai'
 *  @param {string} text  Initial text content
 *  @param {string|null} ts  ISO timestamp string (optional; defaults to now)
 */
function _createBubble(role, text, ts) {
  const bubble = document.createElement('div');
  // role is 'user' → chat-user; 'ai' → chat-ai
  const roleClass = role === 'user' ? 'chat-user' : 'chat-ai';
  bubble.className = `chat-bubble ${roleClass}`;
  const isoTs = ts || new Date().toISOString();
  bubble.dataset.ts = isoTs;

  const textEl = document.createElement('span');
  textEl.className = 'chat-text';
  textEl.textContent = text;

  const tsEl = document.createElement('span');
  tsEl.className = 'chat-timestamp';
  tsEl.textContent = formatRelativeTime(isoTs);

  bubble.appendChild(textEl);
  bubble.appendChild(tsEl);
  return bubble;
}

// Current plan state for real-time budget bar updates
let _currentPlanBudget = 0;

// Persisted search result data — survive plan updates so sections stay visible
let _lastHotels = null;
let _lastFlights = null;
let _lastPlaces = null;

// Persisted suggestions — survive plan updates
let _lastSuggestions = null;

// ---------------------------------------------------------------------------
// SSE reconnect — exponential backoff configuration
// ---------------------------------------------------------------------------

const _SSE_MAX_RETRIES = 3;
const _SSE_RETRY_BASE_MS = 1000; // 1s → 2s → 4s
let _sseRetryCount = 0;

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

const _SESSION_STORAGE_KEY = 'chatSessionId';

async function initChatSession() {
  // 1. Check localStorage for a previously saved session ID.
  const savedId = typeof localStorage !== 'undefined'
    ? localStorage.getItem(_SESSION_STORAGE_KEY) : null;
  if (savedId) {
    try {
      const verifyRes = await fetch(`/chat/sessions/${savedId}`);
      if (verifyRes.ok) {
        chatSessionId = savedId;
        return; // Reuse the existing session.
      }
      // Session expired or not found on the server — remove stale entry.
      localStorage.removeItem(_SESSION_STORAGE_KEY);
    } catch (_e) {
      // Network error during verify — fall through to create a new session.
      localStorage.removeItem(_SESSION_STORAGE_KEY);
    }
  }

  // 2. Create a new session and persist its ID.
  try {
    const res = await fetch('/chat/sessions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    chatSessionId = data.session_id;
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(_SESSION_STORAGE_KEY, chatSessionId);
    }
  } catch (e) {
    console.error('[chat] session init failed:', e);
    chatSessionId = null;
  }
}

// ---------------------------------------------------------------------------
// Session state restore — called after SSE reconnect
// ---------------------------------------------------------------------------

async function restoreSessionState() {
  if (!chatSessionId) return;
  try {
    const res = await fetch(`/chat/sessions/${chatSessionId}`);
    if (!res.ok) return;
    const data = await res.json();
    // Restore last known agent statuses
    if (data.agent_states && typeof data.agent_states === 'object') {
      for (const state of Object.values(data.agent_states)) {
        handleAgentStatus(state);
      }
    }
    // Restore last plan
    if (data.last_plan) {
      handlePlanUpdate(data.last_plan);
    }
    // Restore message bubbles from DB history
    if (data.message_history && data.message_history.length > 0) {
      _restoreMessageBubbles(data.message_history);
    }
  } catch (e) {
    console.warn('[chat] restoreSessionState failed:', e);
  }
}

// Prepend historical chat bubbles into #chat-messages.
// Skips if already restored (idempotent via data-restored attribute).
function _restoreMessageBubbles(history) {
  const messagesEl = document.getElementById('chat-messages');
  if (!messagesEl) return;
  // Idempotent: skip if we already prepended restored bubbles
  if (messagesEl.querySelector('.chat-bubble[data-restored]')) return;

  const fragment = document.createDocumentFragment();
  for (const msg of history) {
    const role = msg.role === 'user' ? 'user' : 'ai';
    const bubble = _createBubble(role, msg.content || '', msg.created_at || null);
    bubble.dataset.restored = '1';
    fragment.appendChild(bubble);
  }
  messagesEl.insertBefore(fragment, messagesEl.firstChild);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---------------------------------------------------------------------------
// sendChatMessage — overrides stub in index.html
// ---------------------------------------------------------------------------

async function sendChatMessage() {
  const input = document.getElementById('chat-input');
  if (!input || !input.value.trim()) return;
  const msg = input.value.trim();
  input.value = '';
  input.disabled = true;

  // Append user bubble
  const messagesEl = document.getElementById('chat-messages');
  if (messagesEl) {
    const bubble = _createBubble('user', msg);
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // Ensure session exists
  if (!chatSessionId) {
    await initChatSession();
  }
  if (!chatSessionId) {
    appendAiBubble('세션 생성에 실패했습니다. 페이지를 새로고침해주세요.');
    input.disabled = false;
    return;
  }

  // Reset agent cards to idle and reconnect counter
  resetAgentCards();
  _sseRetryCount = 0;

  // Create empty AI bubble — text is appended by chat_chunk events
  currentStreamBubble = appendAiBubble('');

  await _sendMessageWithRetry(msg);

  input.disabled = false;
  if (input.focus) input.focus();
}

// Internal: POST message + stream SSE, retrying on disconnect with exponential backoff.
async function _sendMessageWithRetry(msg) {
  while (_sseRetryCount <= _SSE_MAX_RETRIES) {
    // On retries (not the first attempt), restore session state before re-sending
    if (_sseRetryCount > 0) {
      const backoffMs = _SSE_RETRY_BASE_MS * Math.pow(2, _sseRetryCount - 1);
      await new Promise(r => setTimeout(r, backoffMs));
      await restoreSessionState();
    }

    let chatDoneReceived = false;
    try {
      const res = await fetch(`/chat/sessions/${chatSessionId}/messages`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: msg}),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (currentStreamBubble) {
          _setBubbleText(currentStreamBubble, `오류: ${err.detail || res.status}`);
        }
        currentStreamBubble = null;
        return; // HTTP error — don't retry (session may be gone)
      }

      chatDoneReceived = await streamSseResponse(res.body);
    } catch (e) {
      // Network/stream error — will retry if under limit
      console.warn(`[chat] SSE error (attempt ${_sseRetryCount + 1}):`, e);
    }

    if (chatDoneReceived) {
      return; // Stream completed normally
    }

    _sseRetryCount++;
    if (_sseRetryCount > _SSE_MAX_RETRIES) {
      if (currentStreamBubble) {
        _setBubbleText(currentStreamBubble, '연결이 끊겼습니다. 페이지를 새로고침 후 다시 시도해주세요.');
      }
      currentStreamBubble = null;
      return;
    }
  }
}

// ---------------------------------------------------------------------------
// SSE stream reader
// ---------------------------------------------------------------------------

// Returns true if the stream completed with a chat_done event (normal end),
// or false if the connection dropped before chat_done (triggers retry).
async function streamSseResponse(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let chatDoneReceived = false;

  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      const lines = buf.split('\n');
      buf = lines.pop(); // keep incomplete trailing line
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6));
            if (event && event.type === 'chat_done') chatDoneReceived = true;
            handleSseEvent(event);
          } catch (_) { /* ignore malformed JSON */ }
        }
      }
    }
    // Flush remaining buffer
    if (buf.startsWith('data: ')) {
      try {
        const event = JSON.parse(buf.slice(6));
        if (event && event.type === 'chat_done') chatDoneReceived = true;
        handleSseEvent(event);
      } catch (_) {}
    }
  } finally {
    reader.releaseLock();
  }

  return chatDoneReceived;
}

// ---------------------------------------------------------------------------
// SSE event dispatcher
// ---------------------------------------------------------------------------

function handleSseEvent(event) {
  if (!event || !event.type) return;
  switch (event.type) {
    case 'agent_status':
      if (event.data) handleAgentStatus(event.data);
      break;
    case 'chat_chunk':
      if (currentStreamBubble && event.data && event.data.text) {
        _appendBubbleText(currentStreamBubble, event.data.text);
        const el = document.getElementById('chat-messages');
        if (el) el.scrollTop = el.scrollHeight;
      }
      break;
    case 'chat_done':
      currentStreamBubble = null;
      break;
    case 'plan_update':
      if (event.data) handlePlanUpdate(event.data);
      break;
    case 'day_update':
      if (event.data) handleDayUpdate(event.data);
      break;
    case 'search_results':
      if (event.data) handleSearchResults(event.data);
      break;
    case 'weather_data':
      if (event.data) handleWeatherData(event.data);
      break;
    case 'plans_list':
      if (event.data) handlePlansList(event.data);
      break;
    case 'calendar_exported':
      if (event.data) {
        const count = event.data.events_created != null ? event.data.events_created : 0;
        const dest = event.data.destination ? ` — ${event.data.destination}` : '';
        appendAiBubble(`✅ Google Calendar 내보내기 완료${dest}: ${count}개 이벤트 추가됨`);
      }
      break;
    case 'plan_saved':
      appendAiBubble('✅ ' + ((event.data && event.data.message) || '저장 완료'));
      if (event.data && event.data.plan) {
        _appendSavedPlanCard(event.data.plan);
      }
      break;
    case 'plan_deleted': {
      const panel = document.getElementById('plan-panel');
      if (panel) {
        panel.innerHTML = '<div class="meta">여행 계획이 삭제되었습니다.</div>';
      }
      break;
    }
    case 'expense_added':
      if (event.data) handleExpenseAdded(event.data);
      break;
    case 'expense_updated':
      if (event.data) handleExpenseUpdated(event.data);
      break;
    case 'expense_deleted':
      if (event.data) handleExpenseDeleted(event.data);
      break;
    case 'expense_summary':
      if (event.data) handleExpenseSummary(event.data);
      break;
    case 'expense_list':
      if (event.data) handleExpenseList(event.data);
      break;
    case 'plan_suggestions':
      if (event.data) handlePlanSuggestions(event.data);
      break;
    case 'plan_shared':
      if (event.data) handlePlanShared(event.data);
      break;
    case 'session_reset':
      _handleSessionReset();
      break;
    case 'error': {
      const errMsg = (event.data && event.data.message) || '오류 발생';
      if (currentStreamBubble) {
        _setBubbleText(currentStreamBubble, `⚠️ ${errMsg}`);
        currentStreamBubble = null;
      } else {
        appendAiBubble(`⚠️ ${errMsg}`);
      }
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// Agent card helpers
// ---------------------------------------------------------------------------

function resetAgentCards() {
  document.querySelectorAll('[data-agent]').forEach(el => {
    el.className = 'agent-card agent-idle';
    el.style.cursor = '';
    el.onclick = null;
    const msgEl = el.querySelector('.agent-message');
    if (msgEl) msgEl.textContent = '대기 중';
    const spinner = el.querySelector('.agent-spinner');
    if (spinner) spinner.style.display = 'none';
    const toggleEl = el.querySelector('.agent-toggle');
    if (toggleEl) { toggleEl.style.display = 'none'; toggleEl.textContent = '▾'; }
    const detail = el.querySelector('.agent-detail');
    if (detail) detail.style.display = 'none';
  });
  checkAgentPanelState();
}

// ---------------------------------------------------------------------------
// Agent panel compact/expanded toggle
// ---------------------------------------------------------------------------

// Collapses to one compact row when all agents are idle;
// auto-expands when any agent becomes active.
function checkAgentPanelState() {
  const cards = document.querySelectorAll('[data-agent]');
  const allIdle = Array.from(cards).every(c => c.classList.contains('agent-idle'));
  const compactRow = document.getElementById('agent-panel-compact-row');
  const cardsContainer = document.getElementById('agent-cards');
  if (!compactRow || !cardsContainer) return;
  if (allIdle) {
    compactRow.style.display = 'flex';
    cardsContainer.style.display = 'none';
  } else {
    compactRow.style.display = 'none';
    cardsContainer.style.display = 'block';
  }
}

// handleAgentStatus is also defined in index.html; this version is loaded
// later so it takes precedence. It also manages the expandable result toggle,
// done-card click-to-reveal, and compact/expanded panel state.
function handleAgentStatus(data) {
  const el = document.querySelector(`[data-agent="${data.agent}"]`);
  if (!el) return;
  el.className = `agent-card agent-${data.status}`;
  const msgEl = el.querySelector('.agent-message');
  if (msgEl) msgEl.textContent = data.message || '';
  const spinner = el.querySelector('.agent-spinner');
  if (spinner) spinner.style.display = data.status === 'working' ? 'inline-block' : 'none';

  // Show expand toggle when agent has results
  const toggleEl = el.querySelector('.agent-toggle');
  if (toggleEl) {
    if (data.status === 'done' && data.result_count) {
      toggleEl.style.display = 'inline';
      toggleEl.textContent = '▾';
    } else {
      toggleEl.style.display = 'none';
    }
  }

  // Done-state cards: clicking the card reveals/hides the agent-detail panel
  if (data.status === 'done') {
    el.style.cursor = 'pointer';
    el.onclick = function() {
      const detail = el.querySelector('.agent-detail');
      if (!detail) return;
      const isHidden = detail.style.display === 'none' || !detail.style.display;
      detail.style.display = isHidden ? 'block' : 'none';
      if (toggleEl) toggleEl.textContent = isHidden ? '▴' : '▾';
    };
  } else {
    el.style.cursor = '';
    el.onclick = null;
  }

  checkAgentPanelState();
}

// ---------------------------------------------------------------------------
// Chat bubble helpers
// ---------------------------------------------------------------------------

function _handleSessionReset() {
  const messagesEl = document.getElementById('chat-messages');
  if (messagesEl) messagesEl.innerHTML = '';
  currentStreamBubble = null;
  resetAgentCards();
}

function appendAiBubble(text, ts) {
  const messagesEl = document.getElementById('chat-messages');
  if (!messagesEl) return null;
  const bubble = _createBubble('ai', text, ts || null);
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

// ---------------------------------------------------------------------------
// Dashboard panel renderers
// ---------------------------------------------------------------------------

function _hotelCardHtml(h) {
  return `<div class="search-result-card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>${escHtml(h.name)}</strong>
      ${h.price_range ? `<span class="price-tag">${escHtml(h.price_range)}</span>` : ''}
    </div>
    ${h.rating ? `<div class="meta">⭐ ${escHtml(String(h.rating))}</div>` : ''}
    ${h.address ? `<div class="meta" style="font-size:.75rem">${escHtml(h.address)}</div>` : ''}
  </div>`;
}

function _flightCardHtml(f) {
  const route = (f.departure_time && f.arrival_time)
    ? `${escHtml(f.departure_time)} → ${escHtml(f.arrival_time)}` : '';
  return `<div class="search-result-card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>${escHtml(f.airline)}</strong>
      ${f.price ? `<span class="price-tag">${escHtml(String(f.price))}</span>` : ''}
    </div>
    ${f.flight_number ? `<div class="meta">${escHtml(f.flight_number)}${f.stops ? ` · ${escHtml(f.stops)}` : ''}</div>` : ''}
    ${route ? `<div class="meta">${route}${f.duration ? ` (${escHtml(f.duration)})` : ''}</div>` : ''}
  </div>`;
}

function _placeScoutCardHtml(p) {
  return `<div class="search-result-card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>${escHtml(p.name)}</strong>
      ${p.estimated_cost ? `<span class="price-tag">$${p.estimated_cost}</span>` : ''}
    </div>
    ${p.category ? `<div class="meta">${escHtml(p.category)}</div>` : ''}
    ${p.address ? `<div class="meta" style="font-size:.75rem">${escHtml(p.address)}</div>` : ''}
  </div>`;
}

// Appends or refreshes dedicated #plan-hotels-section / #plan-flights-section /
// #plan-places-section inside panel.
// Each section is hidden when there is no data and visible when data is present.
function _refreshPlanSearchSections(panel) {
  if (!panel) return;

  // Hotels section
  let hotelsEl = panel.querySelector('#plan-hotels-section');
  if (_lastHotels && _lastHotels.length) {
    if (!hotelsEl) {
      hotelsEl = document.createElement('div');
      hotelsEl.id = 'plan-hotels-section';
      hotelsEl.className = 'plan-search-section';
      panel.appendChild(hotelsEl);
    }
    hotelsEl.innerHTML = `<div class="section-title">🏨 Hotels</div>` +
      _lastHotels.map(h => _hotelCardHtml(h)).join('');
    hotelsEl.style.display = '';
  } else if (hotelsEl) {
    hotelsEl.style.display = 'none';
  }

  // Flights section
  let flightsEl = panel.querySelector('#plan-flights-section');
  if (_lastFlights && _lastFlights.length) {
    if (!flightsEl) {
      flightsEl = document.createElement('div');
      flightsEl.id = 'plan-flights-section';
      flightsEl.className = 'plan-search-section';
      panel.appendChild(flightsEl);
    }
    flightsEl.innerHTML = `<div class="section-title">✈️ Flights</div>` +
      _lastFlights.map(f => _flightCardHtml(f)).join('');
    flightsEl.style.display = '';
  } else if (flightsEl) {
    flightsEl.style.display = 'none';
  }

  // Places section (below Hotels and Flights)
  let placesEl = panel.querySelector('#plan-places-section');
  if (_lastPlaces && _lastPlaces.length) {
    if (!placesEl) {
      placesEl = document.createElement('div');
      placesEl.id = 'plan-places-section';
      placesEl.className = 'plan-search-section';
      panel.appendChild(placesEl);
    }
    placesEl.innerHTML = `<div class="section-title">📍 Places</div>` +
      _lastPlaces.map(p => _placeScoutCardHtml(p)).join('');
    placesEl.style.display = '';
  } else if (placesEl) {
    placesEl.style.display = 'none';
  }
}

function _budgetBarHtml(spent, budget) {
  if (!budget) return '';
  const pct = Math.min(100, (spent / budget) * 100).toFixed(1);
  const barColor = pct >= 90 ? '#dc3545' : pct >= 70 ? '#ffc107' : '#198754';
  return `<div class="budget-row">
    <span class="meta">예상 비용: <strong>$${Math.round(spent).toLocaleString()}</strong></span>
    <span class="meta">예산: $${Math.round(budget).toLocaleString()}</span>
  </div>
  <div class="progress-bar-bg" style="margin:.4rem 0 .2rem">
    <div class="progress-bar" id="plan-budget-bar" style="width:${pct}%;background:${barColor}"></div>
  </div>
  <div class="meta">${pct}% 사용</div>`;
}

function handlePlanUpdate(data) {
  const panel = document.getElementById('plan-panel');
  if (!panel || !data.days || !data.days.length) return;

  _currentPlanBudget = data.budget || 0;
  const cost = data.total_estimated_cost || 0;

  let html = `<div class="section-title">✈️ Travel Plan</div>`;

  // Plan overview: destination + dates
  if (data.destination || data.start_date) {
    const dest = data.destination ? escHtml(data.destination) : '';
    const dates = (data.start_date && data.end_date)
      ? `${escHtml(data.start_date)} → ${escHtml(data.end_date)}`
      : '';
    html += `<div class="plan-overview">
      ${dest ? `<strong class="plan-dest">${dest}</strong>` : ''}
      ${dates ? `<span class="meta">${dates}</span>` : ''}
    </div>`;
  }

  // Budget bar
  if (_currentPlanBudget > 0) {
    html += `<div class="plan-budget">${_budgetBarHtml(cost, _currentPlanBudget)}</div>`;
  }

  // Day cards
  for (const day of data.days) {
    html += _dayCardHtml(day);
  }
  panel.innerHTML = html;

  // Re-append hotels/flights sections (persist across plan updates)
  _refreshPlanSearchSections(panel);
}

function _dayCardHtml(day) {
  const places = (day.places || []).map(p => _placeItemHtml(p)).join('');
  const dayCost = (day.places || []).reduce((s, p) => s + (p.estimated_cost || 0), 0);
  return `<div class="card day-card" id="day-${escHtml(day.date)}">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>${escHtml(day.date)}</strong>
      ${dayCost > 0 ? `<span class="price-tag">$${dayCost.toLocaleString()}</span>` : ''}
    </div>
    ${day.notes ? `<div class="meta">${escHtml(day.notes)}</div>` : ''}
    <div class="day-places">${places || '<div class="meta">장소 없음</div>'}</div>
  </div>`;
}

function _placeItemHtml(p) {
  return `<div class="place-item">
    <div>
      <span>${escHtml(p.name)}</span>
      ${p.category ? `<span class="meta" style="margin-left:.4rem">(${escHtml(p.category)})</span>` : ''}
    </div>
    ${p.estimated_cost ? `<span class="price-tag">$${p.estimated_cost}</span>` : ''}
  </div>`;
}

function handleDayUpdate(data) {
  let dayEl = document.getElementById(`day-${data.date}`);
  if (!dayEl) {
    // Day card may not exist yet — create it inside plan-panel
    const panel = document.getElementById('plan-panel');
    if (!panel) return;
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = _dayCardHtml(data);
    dayEl = tempDiv.firstElementChild;
    panel.appendChild(dayEl);
    return;
  }
  const placesEl = dayEl.querySelector('.day-places');
  if (placesEl && data.places) {
    placesEl.innerHTML = data.places.map(p => _placeItemHtml(p)).join('');
  }
  // Update day cost
  const dayCost = (data.places || []).reduce((s, p) => s + (p.estimated_cost || 0), 0);
  const costEl = dayEl.querySelector('.price-tag');
  if (dayCost > 0) {
    if (costEl) {
      costEl.textContent = `$${dayCost.toLocaleString()}`;
    }
  }
}

// ---------------------------------------------------------------------------
// Search results → agent expandable detail panel
// ---------------------------------------------------------------------------

const _SEARCH_AGENT = {hotels: 'hotel_finder', flights: 'flight_finder', places: 'place_scout', budget: 'budget_analyst'};

function handleSearchResults(data) {
  const agentId = _SEARCH_AGENT[data.type];
  const agentEl = agentId ? document.querySelector(`[data-agent="${agentId}"]`) : null;
  const results = data.results || {};

  let itemsHtml = '';
  if (data.type === 'hotels' && results.hotels) {
    _lastHotels = results.hotels;
    itemsHtml = results.hotels.map(h => _hotelCardHtml(h)).join('');
  } else if (data.type === 'flights' && results.flights) {
    _lastFlights = results.flights;
    itemsHtml = results.flights.map(f => _flightCardHtml(f)).join('');
  } else if (data.type === 'places' && results.places) {
    _lastPlaces = results.places;
    itemsHtml = results.places.map(p => _placeScoutCardHtml(p)).join('');
  } else if (data.type === 'budget') {
    const cats = [
      {key: 'accommodation', label: '🏨 숙소'},
      {key: 'transport',     label: '🚌 교통'},
      {key: 'food',          label: '🍜 식비'},
      {key: 'activities',    label: '🎯 활동'},
      {key: 'total',         label: '💰 합계'},
    ];
    itemsHtml = `<div class="budget-breakdown">` +
      cats.map(c => {
        const val = results[c.key];
        const valStr = (val != null) ? `$${Math.round(val).toLocaleString()}` : '-';
        return `<div class="budget-breakdown-row" style="display:flex;justify-content:space-between;padding:.2rem 0${c.key==='total'?';font-weight:bold;border-top:1px solid #ccc;margin-top:.3rem':''}">
          <span>${c.label}</span><span>${valStr}</span></div>`;
      }).join('') +
      `</div>`;
  }

  // Append to agent detail panel (expandable)
  if (agentEl) {
    let detailEl = agentEl.querySelector('.agent-detail');
    if (!detailEl) {
      detailEl = document.createElement('div');
      detailEl.className = 'agent-detail';
      agentEl.appendChild(detailEl);
    }
    detailEl.innerHTML = itemsHtml;
    detailEl.style.display = 'none'; // collapsed by default; toggle on ▾ click
  }

  // Update plan-panel: hotels/flights/places get dedicated persistent sections.
  const planPanel = document.getElementById('plan-panel');
  if (data.type === 'hotels' || data.type === 'flights' || data.type === 'places') {
    _refreshPlanSearchSections(planPanel);
  }
}

// ---------------------------------------------------------------------------
// Weather data panel — persists in dashboard across messages
// ---------------------------------------------------------------------------

function handleWeatherData(data) {
  const dashboardCol = document.querySelector('.dashboard-col');
  if (!dashboardCol) return;

  let panel = dashboardCol.querySelector('.weather-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.className = 'weather-panel card';
    dashboardCol.appendChild(panel);
  }

  const city = escHtml(data.destination || '');
  const summary = escHtml(data.summary || '');
  const forecast = Array.isArray(data.forecast) ? data.forecast : [];

  const forecastRows = forecast.map(row => {
    const dateStr = escHtml(row.date || '');
    const high = escHtml(row.temperature_high || '');
    const low = escHtml(row.temperature_low || '');
    const condition = escHtml(row.description || row.condition || '');
    const temps = (high || low) ? `${high} / ${low}` : '';
    return `<div class="weather-forecast-row">
      <span class="weather-forecast-date">${dateStr}</span>
      <span class="weather-forecast-condition">${condition}</span>
      <span class="weather-forecast-temps">${temps}</span>
    </div>`;
  }).join('');

  panel.innerHTML = `
    <div class="weather-panel-title">🌤 날씨 예보</div>
    <div class="weather-city">${city}</div>
    ${summary ? `<div class="weather-summary">${summary}</div>` : ''}
    <div class="weather-forecast">${forecastRows || '<div class="meta">날씨 정보 없음</div>'}</div>
  `;
}

// ---------------------------------------------------------------------------
// Saved plans list — renders plan cards; click to load as active plan
// ---------------------------------------------------------------------------

function handlePlansList(data) {
  const panel = document.getElementById('plan-panel');
  if (!panel) return;
  const plans = data.plans || [];
  if (!plans.length) {
    panel.innerHTML = '<div class="section-title">📋 Saved Plans</div><div class="meta">저장된 여행 계획이 없습니다.</div>';
    return;
  }
  let html = '<div class="section-title">📋 Saved Plans</div>';
  for (const plan of plans) {
    const dest   = escHtml(plan.destination || '');
    const dates  = (plan.start_date && plan.end_date)
      ? `${escHtml(plan.start_date)} → ${escHtml(plan.end_date)}` : '';
    const budget = plan.budget ? `$${Math.round(plan.budget).toLocaleString()}` : '';
    const status = plan.status ? escHtml(plan.status) : '';
    html += `<div class="card plan-saved-card" data-plan-id="${escHtml(String(plan.id ?? ''))}"
        style="cursor:pointer;margin-bottom:.5rem" role="button" tabindex="0">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong>${dest}</strong>
        ${budget ? `<span class="price-tag">${budget}</span>` : ''}
      </div>
      ${dates  ? `<div class="meta">${dates}</div>`  : ''}
      ${status ? `<div class="meta">${status}</div>` : ''}
    </div>`;
  }
  panel.innerHTML = html;

  // Attach click + keyboard handlers
  panel.querySelectorAll('.plan-saved-card').forEach(card => {
    const planId = card.dataset.planId;
    const plan = plans.find(p => String(p.id) === planId);
    if (!plan) return;
    const activate = () => _activateSavedPlan(plan, card);
    card.addEventListener('click', activate);
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') activate(); });
  });
}

function _activateSavedPlan(plan, cardEl) {
  // Highlight the selected card
  document.querySelectorAll('.plan-saved-card').forEach(c => c.classList.remove('plan-card-active'));
  if (cardEl) cardEl.classList.add('plan-card-active');

  _currentPlanBudget = plan.budget || 0;

  // Render plan overview in the plan-panel
  const panel = document.getElementById('plan-panel');
  if (!panel) return;
  const dest  = plan.destination ? escHtml(plan.destination) : '';
  const dates = (plan.start_date && plan.end_date)
    ? `${escHtml(plan.start_date)} → ${escHtml(plan.end_date)}` : '';
  let html = `<div class="section-title">✈️ Travel Plan</div>`;
  if (dest || dates) {
    html += `<div class="plan-overview">
      ${dest  ? `<strong class="plan-dest">${dest}</strong>` : ''}
      ${dates ? `<span class="meta">${dates}</span>` : ''}
    </div>`;
  }
  if (_currentPlanBudget > 0) {
    html += `<div class="plan-budget">${_budgetBarHtml(0, _currentPlanBudget)}</div>`;
  }
  const planLabel = plan.id != null ? ` #${plan.id}` : '';
  html += `<div class="meta" style="margin-top:.5rem">저장된 계획${escHtml(String(planLabel))} — 일정을 생성하려면 "일정 만들어줘"라고 입력하세요.</div>`;
  panel.innerHTML = html;

  // Re-append hotels/flights sections if they exist from a prior search
  _refreshPlanSearchSections(panel);
}

// ---------------------------------------------------------------------------
// Expense added — update budget section + expense list in plan-panel
// ---------------------------------------------------------------------------

function handleExpenseAdded(data) {
  const expense   = data.expense || {};
  const summary   = data.budget_summary || {};
  const panel     = document.getElementById('plan-panel');
  if (!panel) return;

  // Update budget bar if present
  const budgetDiv = panel.querySelector('.plan-budget');
  const budget    = summary.budget || _currentPlanBudget;
  const spent     = summary.total_spent || 0;
  if (budget > 0) {
    if (budgetDiv) {
      budgetDiv.innerHTML = _budgetBarHtml(spent, budget);
    } else {
      const newBudget = document.createElement('div');
      newBudget.className = 'plan-budget';
      newBudget.innerHTML = _budgetBarHtml(spent, budget);
      const firstChild = panel.firstElementChild;
      if (firstChild) {
        firstChild.after(newBudget);
      } else {
        panel.appendChild(newBudget);
      }
    }
  }

  // Upsert the expense list section
  let expenseSection = panel.querySelector('.expense-section');
  if (!expenseSection) {
    expenseSection = document.createElement('div');
    expenseSection.className = 'expense-section';
    expenseSection.innerHTML = '<div class="section-title">💸 Expenses</div><div class="expense-list"></div>';
    panel.appendChild(expenseSection);
  }

  const listEl = expenseSection.querySelector('.expense-list');
  if (listEl && expense.name != null) {
    const row = document.createElement('div');
    row.className = 'place-item';
    const cat = expense.category ? ` <span class="meta">(${escHtml(expense.category)})</span>` : '';
    row.innerHTML = `<div><span>${escHtml(String(expense.name))}</span>${cat}</div>` +
      `<span class="price-tag">${Number(expense.amount).toLocaleString()}원</span>`;
    listEl.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Expense deleted — remove matching row from expense list + update budget bar
// ---------------------------------------------------------------------------

function handleExpenseDeleted(data) {
  const name    = data.name;
  const summary = data.budget_summary || {};
  const panel   = document.getElementById('plan-panel');
  if (!panel) return;

  // Remove the last row in .expense-list whose name span matches
  const listEl = panel.querySelector('.expense-list');
  if (listEl && name != null) {
    const rows = listEl.querySelectorAll('.place-item');
    // Walk in reverse to remove the most-recently-added matching row
    for (let i = rows.length - 1; i >= 0; i--) {
      const nameSpan = rows[i].querySelector('div > span:first-child');
      if (nameSpan && nameSpan.textContent === String(name)) {
        rows[i].remove();
        break;
      }
    }
  }

  // Update budget bar
  const budget = summary.budget || _currentPlanBudget;
  const spent  = summary.total_spent || 0;
  if (budget > 0) {
    const budgetDiv = panel.querySelector('.plan-budget');
    if (budgetDiv) {
      budgetDiv.innerHTML = _budgetBarHtml(spent, budget);
    }
  }
}

// ---------------------------------------------------------------------------
// Expense updated — update matching row in expense list + update budget bar
// ---------------------------------------------------------------------------

function handleExpenseUpdated(data) {
  const expense = data.expense || {};
  const summary = data.budget_summary || {};
  const panel   = document.getElementById('plan-panel');
  if (!panel) return;

  // Update the matching row (find by name)
  const listEl = panel.querySelector('.expense-list');
  if (listEl && expense.name != null) {
    const rows = listEl.querySelectorAll('.place-item');
    for (let i = rows.length - 1; i >= 0; i--) {
      const nameSpan = rows[i].querySelector('div > span:first-child');
      if (nameSpan && nameSpan.textContent === String(expense.name)) {
        const cat = expense.category ? ` <span class="meta">(${escHtml(expense.category)})</span>` : '';
        rows[i].innerHTML = `<div><span>${escHtml(String(expense.name))}</span>${cat}</div>` +
          `<span class="price-tag">${Number(expense.amount).toLocaleString()}원</span>`;
        break;
      }
    }
  }

  // Update budget bar
  const budget = summary.budget || _currentPlanBudget;
  const spent  = summary.total_spent || 0;
  if (budget > 0) {
    const budgetDiv = panel.querySelector('.plan-budget');
    if (budgetDiv) {
      budgetDiv.innerHTML = _budgetBarHtml(spent, budget);
    }
  }
}

function handleExpenseSummary(data) {
  const panel = document.getElementById('plan-panel');
  if (!panel) return;

  const budget  = data.budget || 0;
  const spent   = data.total_spent || 0;
  const remaining = (data.remaining != null) ? data.remaining : (budget - spent);

  // Update budget bar
  if (budget > 0) {
    const budgetDiv = panel.querySelector('.plan-budget');
    const html = _budgetBarHtml(spent, budget);
    if (budgetDiv) {
      budgetDiv.innerHTML = html;
    } else {
      const newBudget = document.createElement('div');
      newBudget.className = 'plan-budget';
      newBudget.innerHTML = html;
      const firstChild = panel.firstElementChild;
      if (firstChild) firstChild.after(newBudget);
      else panel.appendChild(newBudget);
    }
  }

  // Upsert expense summary section
  let summarySection = panel.querySelector('.expense-summary-section');
  if (!summarySection) {
    summarySection = document.createElement('div');
    summarySection.className = 'expense-summary-section';
    panel.appendChild(summarySection);
  }

  const byCategory = data.by_category || {};
  const catRows = Object.entries(byCategory).map(([cat, amt]) =>
    `<div class="place-item"><span>${escHtml(cat)}</span><span class="price-tag">${Number(amt).toLocaleString()}원</span></div>`
  ).join('');
  const overStyle = data.over_budget ? ' style="color:red"' : '';

  summarySection.innerHTML =
    '<div class="section-title">💰 지출 요약</div>' +
    `<div class="place-item"><span>총 지출</span><span class="price-tag"${overStyle}>${Number(spent).toLocaleString()}원${data.over_budget ? ' ⚠️' : ''}</span></div>` +
    `<div class="place-item"><span>남은 예산</span><span class="price-tag">${Number(remaining).toLocaleString()}원</span></div>` +
    (catRows ? '<div class="section-title" style="font-size:.8rem;margin-top:.4rem">카테고리별</div>' + catRows : '');
}

// ---------------------------------------------------------------------------
// Expense panel — dedicated section below budget tracker in plan-panel
// expense_list SSE event triggers full re-render as a table with edit/delete
// ---------------------------------------------------------------------------

// Prefill the chat input with a message (for edit/delete row actions)
function prefillChatInput(text) {
  const input = document.getElementById('chat-input');
  if (!input) return;
  input.value = text;
  input.focus();
}

function handleExpenseList(data) {
  const expenses = data.expenses || [];
  const panel    = document.getElementById('plan-panel');
  if (!panel) return;

  // Get or create the .expense-panel section
  let expensePanel = panel.querySelector('.expense-panel');
  if (!expensePanel) {
    expensePanel = document.createElement('div');
    expensePanel.className = 'expense-panel';
    // Insert below .plan-budget if present, otherwise append
    const budgetDiv = panel.querySelector('.plan-budget');
    if (budgetDiv && budgetDiv.nextSibling) {
      panel.insertBefore(expensePanel, budgetDiv.nextSibling);
    } else if (budgetDiv) {
      panel.appendChild(expensePanel);
    } else {
      panel.appendChild(expensePanel);
    }
  }

  // Hide panel when there are no expenses
  if (!expenses.length) {
    expensePanel.style.display = 'none';
    return;
  }
  expensePanel.style.display = '';

  // Build table rows
  const rows = expenses.map(e => {
    const id       = e.id != null ? escHtml(String(e.id)) : '';
    const name     = escHtml(String(e.name || ''));
    const amount   = Number(e.amount || 0).toLocaleString();
    const category = e.category ? escHtml(String(e.category)) : '—';
    const date     = e.date ? escHtml(String(e.date)) : '—';
    // Edit prefill: "지출 수정 {id} {name} {amount}"
    const editMsg  = `지출 수정 ${e.id} ${e.name} ${e.amount}`;
    // Delete prefill: "지출 삭제 {id} {name}"
    const delMsg   = `지출 삭제 ${e.id} ${e.name}`;
    return `<tr>
      <td>${name}</td>
      <td class="price-tag">${amount}원</td>
      <td>${category}</td>
      <td>${date}</td>
      <td class="expense-panel-actions">
        <button class="btn btn-outline btn-sm"
          onclick="prefillChatInput(${JSON.stringify(editMsg)})">수정</button>
        <button class="btn btn-danger btn-sm"
          onclick="prefillChatInput(${JSON.stringify(delMsg)})">삭제</button>
      </td>
    </tr>`;
  }).join('');

  expensePanel.innerHTML = `
    <div class="section-title">💸 지출 내역</div>
    <table class="expense-panel-table">
      <thead>
        <tr>
          <th>항목</th><th>금액</th><th>카테고리</th><th>날짜</th><th></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ---------------------------------------------------------------------------
// Plan suggestions panel — rendered by plan_suggestions SSE event
// ---------------------------------------------------------------------------

function handlePlanSuggestions(data) {
  const suggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
  _lastSuggestions = suggestions;

  const dashboardCol = document.querySelector('.dashboard-col');
  if (!dashboardCol) return;

  // Find or create the suggestions panel
  let panel = document.getElementById('suggestions-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'suggestions-panel';
    panel.className = 'suggestions-panel card';
    dashboardCol.appendChild(panel);
  }

  const cards = suggestions.map(s =>
    `<div class="suggestion-card">${escHtml(s)}</div>`
  ).join('');

  panel.innerHTML =
    `<div class="suggestions-header" onclick="toggleSuggestionsPanel()" role="button" tabindex="0" aria-expanded="true">` +
    `<span class="section-title suggestions-title">💡 Suggestions</span>` +
    `<span class="suggestions-toggle">▴</span>` +
    `</div>` +
    `<div class="suggestions-body">${cards || '<div class="meta">제안 없음</div>'}</div>`;

  // Auto-expand on new suggestions
  panel.dataset.collapsed = 'false';
  const body = panel.querySelector('.suggestions-body');
  if (body) body.style.display = '';
}

function toggleSuggestionsPanel() {
  const panel = document.getElementById('suggestions-panel');
  if (!panel) return;
  const body = panel.querySelector('.suggestions-body');
  const toggle = panel.querySelector('.suggestions-toggle');
  const header = panel.querySelector('.suggestions-header');
  if (!body) return;
  const collapsed = panel.dataset.collapsed === 'true';
  panel.dataset.collapsed = collapsed ? 'false' : 'true';
  body.style.display = collapsed ? '' : 'none';
  if (toggle) toggle.textContent = collapsed ? '▴' : '▾';
  if (header) header.setAttribute('aria-expanded', String(collapsed));
}

// ---------------------------------------------------------------------------
// Append a single plan card to the plan-panel (used by plan_saved/copy_plan)
// ---------------------------------------------------------------------------

function _appendSavedPlanCard(plan) {
  const panel = document.getElementById('plan-panel');
  if (!panel) return;
  const dest   = escHtml(plan.destination || '');
  const dates  = (plan.start_date && plan.end_date)
    ? `${escHtml(plan.start_date)} → ${escHtml(plan.end_date)}` : '';
  const budget = plan.budget ? `₩${Math.round(plan.budget).toLocaleString()}` : '';
  const status = plan.status ? escHtml(plan.status) : '';

  if (!panel.querySelector('.plan-saved-header')) {
    const header = document.createElement('div');
    header.className = 'section-title plan-saved-header';
    header.textContent = '📋 복사된 계획';
    panel.appendChild(header);
  }

  const card = document.createElement('div');
  card.className = 'card plan-saved-card';
  card.dataset.planId = String(plan.id ?? '');
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.style.cssText = 'cursor:pointer;margin-bottom:.5rem';
  card.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>${dest}</strong>
      ${budget ? `<span class="price-tag">${budget}</span>` : ''}
    </div>
    ${dates  ? `<div class="meta">${dates}</div>`  : ''}
    ${status ? `<div class="meta">${status}</div>` : ''}`;
  const activate = () => _activateSavedPlan(plan, card);
  card.addEventListener('click', activate);
  card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') activate(); });
  panel.appendChild(card);
}

// ---------------------------------------------------------------------------
// Share plan — render copiable link card in chat + dashboard
// ---------------------------------------------------------------------------

function handlePlanShared(data) {
  const shareUrl = (data && data.share_url) ? data.share_url : '';

  // --- Chat bubble with copiable URL ---
  const messagesEl = document.getElementById('chat-messages');
  if (messagesEl && shareUrl) {
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble chat-ai';

    const label = document.createElement('div');
    label.textContent = '🔗 공유 링크가 생성되었습니다:';
    label.style.marginBottom = '0.4rem';
    bubble.appendChild(label);

    const urlRow = document.createElement('div');
    urlRow.style.cssText = 'display:flex;gap:.4rem;align-items:center;flex-wrap:wrap';

    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.readOnly = true;
    urlInput.value = shareUrl;
    urlInput.setAttribute('aria-label', '공유 링크');
    urlInput.style.cssText = 'flex:1;min-width:0;font-size:.85rem;padding:.25rem .4rem;border:1px solid #ccc;border-radius:4px;background:#f9f9f9';

    const copyBtn = document.createElement('button');
    copyBtn.textContent = '복사';
    copyBtn.style.cssText = 'padding:.25rem .6rem;font-size:.85rem;cursor:pointer;white-space:nowrap';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(shareUrl).then(() => {
        copyBtn.textContent = '✅ 복사됨';
        setTimeout(() => { copyBtn.textContent = '복사'; }, 2000);
      }).catch(() => {
        urlInput.select();
        document.execCommand('copy');
        copyBtn.textContent = '✅ 복사됨';
        setTimeout(() => { copyBtn.textContent = '복사'; }, 2000);
      });
    });

    urlRow.appendChild(urlInput);
    urlRow.appendChild(copyBtn);
    bubble.appendChild(urlRow);
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // --- Dashboard panel share section ---
  const panel = document.getElementById('plan-panel');
  if (panel && shareUrl) {
    // Remove any previous share card
    const prev = panel.querySelector('.plan-share-card');
    if (prev) prev.remove();

    const shareCard = document.createElement('div');
    shareCard.className = 'card plan-share-card';
    shareCard.style.marginTop = '.75rem';
    shareCard.innerHTML = `
      <div class="section-title" style="margin-bottom:.4rem">🔗 공유 링크</div>
      <div style="display:flex;gap:.4rem;align-items:center;flex-wrap:wrap">
        <input type="text" readonly value="${escHtml(shareUrl)}"
          aria-label="공유 링크 (대시보드)"
          style="flex:1;min-width:0;font-size:.8rem;padding:.2rem .35rem;border:1px solid #ccc;border-radius:4px;background:#f9f9f9">
        <button id="share-copy-btn-panel"
          style="padding:.2rem .5rem;font-size:.8rem;cursor:pointer;white-space:nowrap">복사</button>
      </div>`;
    panel.appendChild(shareCard);

    const panelCopyBtn = shareCard.querySelector('#share-copy-btn-panel');
    const panelInput   = shareCard.querySelector('input');
    if (panelCopyBtn && panelInput) {
      panelCopyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(shareUrl).then(() => {
          panelCopyBtn.textContent = '✅ 복사됨';
          setTimeout(() => { panelCopyBtn.textContent = '복사'; }, 2000);
        }).catch(() => {
          panelInput.select();
          document.execCommand('copy');
          panelCopyBtn.textContent = '✅ 복사됨';
          setTimeout(() => { panelCopyBtn.textContent = '복사'; }, 2000);
        });
      });
    }
  }

// ---------------------------------------------------------------------------
// Periodic timestamp refresh — update relative times every 30 s
// ---------------------------------------------------------------------------

setInterval(_updateAllTimestamps, 30000);
}
