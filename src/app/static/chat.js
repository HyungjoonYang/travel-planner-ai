// chat.js — SSE client + chat message UI + agent_status event handler
// Loaded by index.html after the inline script block.
// Overrides the stub sendChatMessage defined in index.html.

'use strict';

let chatSessionId = null;
let currentStreamBubble = null;

// Current plan state for real-time budget bar updates
let _currentPlanBudget = 0;

// ---------------------------------------------------------------------------
// SSE reconnect — exponential backoff configuration
// ---------------------------------------------------------------------------

const _SSE_MAX_RETRIES = 3;
const _SSE_RETRY_BASE_MS = 1000; // 1s → 2s → 4s
let _sseRetryCount = 0;

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function initChatSession() {
  try {
    const res = await fetch('/chat/sessions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    chatSessionId = data.session_id;
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
  } catch (e) {
    console.warn('[chat] restoreSessionState failed:', e);
  }
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
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble chat-user';
    bubble.textContent = msg;
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
          currentStreamBubble.textContent = `오류: ${err.detail || res.status}`;
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
        currentStreamBubble.textContent = '연결이 끊겼습니다. 페이지를 새로고침 후 다시 시도해주세요.';
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
        currentStreamBubble.textContent += event.data.text;
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
      break;
    case 'error':
      const errMsg = (event.data && event.data.message) || '오류 발생';
      if (currentStreamBubble) {
        currentStreamBubble.textContent = `⚠️ ${errMsg}`;
        currentStreamBubble = null;
      } else {
        appendAiBubble(`⚠️ ${errMsg}`);
      }
      break;
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

function appendAiBubble(text) {
  const messagesEl = document.getElementById('chat-messages');
  if (!messagesEl) return null;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble chat-ai';
  bubble.textContent = text;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

// ---------------------------------------------------------------------------
// Dashboard panel renderers
// ---------------------------------------------------------------------------

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
    itemsHtml = results.hotels.map(h =>
      `<div class="search-result-card">
        <div style="display:flex;justify-content:space-between">
          <strong>${escHtml(h.name)}</strong>
          ${h.price_range ? `<span class="price-tag">${escHtml(h.price_range)}</span>` : ''}
        </div>
        ${h.rating ? `<div class="meta">⭐ ${escHtml(String(h.rating))}</div>` : ''}
      </div>`
    ).join('');
  } else if (data.type === 'flights' && results.flights) {
    itemsHtml = results.flights.map(f =>
      `<div class="search-result-card">
        <div style="display:flex;justify-content:space-between">
          <strong>${escHtml(f.airline)}</strong>
          ${f.price ? `<span class="price-tag">${escHtml(String(f.price))}</span>` : ''}
        </div>
      </div>`
    ).join('');
  } else if (data.type === 'places' && results.places) {
    itemsHtml = results.places.map(p =>
      `<div class="search-result-card">
        <strong>${escHtml(p.name)}</strong>
        ${p.category ? `<div class="meta">${escHtml(p.category)}</div>` : ''}
      </div>`
    ).join('');
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

  // Also show a summary section in plan-panel for search-only requests
  const planPanel = document.getElementById('plan-panel');
  const hasDayCards = planPanel && planPanel.querySelector('.day-card');
  if (planPanel && !hasDayCards) {
    const typeLabel = data.type === 'hotels' ? '🏨 Hotels' :
                      data.type === 'flights' ? '✈️ Flights' : '📍 Places';
    planPanel.innerHTML = `<div class="section-title">${typeLabel}</div>${itemsHtml}`;
  }
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
}
