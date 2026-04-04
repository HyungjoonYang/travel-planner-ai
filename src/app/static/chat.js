// chat.js — SSE client + chat message UI + agent_status event handler
// Loaded by index.html after the inline script block.
// Overrides the stub sendChatMessage defined in index.html.

'use strict';

let chatSessionId = null;
let currentStreamBubble = null;

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

  // Reset agent cards to idle
  resetAgentCards();

  // Create empty AI bubble — text is appended by chat_chunk events
  currentStreamBubble = appendAiBubble('');

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
      input.disabled = false;
      return;
    }

    await streamSseResponse(res.body);
  } catch (e) {
    if (currentStreamBubble) {
      currentStreamBubble.textContent = `연결 오류: ${e.message}`;
    }
    currentStreamBubble = null;
  }

  input.disabled = false;
  if (input.focus) input.focus();
}

// ---------------------------------------------------------------------------
// SSE stream reader
// ---------------------------------------------------------------------------

async function streamSseResponse(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

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
            handleSseEvent(JSON.parse(line.slice(6)));
          } catch (_) { /* ignore malformed JSON */ }
        }
      }
    }
    // Flush remaining buffer
    if (buf.startsWith('data: ')) {
      try { handleSseEvent(JSON.parse(buf.slice(6))); } catch (_) {}
    }
  } finally {
    reader.releaseLock();
  }
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
    const msgEl = el.querySelector('.agent-message');
    if (msgEl) msgEl.textContent = '대기 중';
    const spinner = el.querySelector('.agent-spinner');
    if (spinner) spinner.style.display = 'none';
  });
}

// handleAgentStatus is also defined in index.html; this version is identical
// but loaded later so it takes precedence.
function handleAgentStatus(data) {
  const el = document.querySelector(`[data-agent="${data.agent}"]`);
  if (!el) return;
  el.className = `agent-card agent-${data.status}`;
  const msgEl = el.querySelector('.agent-message');
  if (msgEl) msgEl.textContent = data.message || '';
  const spinner = el.querySelector('.agent-spinner');
  if (spinner) spinner.style.display = data.status === 'working' ? 'inline-block' : 'none';
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

function handlePlanUpdate(data) {
  const panel = document.getElementById('plan-panel');
  if (!panel || !data.days || !data.days.length) return;
  let html = `<div class="section-title">✈️ Travel Plan</div>
    <div class="meta">${data.days.length}일 일정 · 예산 $${(data.total_estimated_cost || 0).toLocaleString()}</div>`;
  for (const day of data.days) {
    const places = (day.places || []).map(p =>
      `<div class="place-item">
        <span>${escHtml(p.name)}</span>
        ${p.estimated_cost ? `<span class="price-tag">$${p.estimated_cost}</span>` : ''}
      </div>`
    ).join('');
    html += `<div class="card" id="day-${escHtml(day.date)}">
      <strong>${escHtml(day.date)}</strong>
      ${day.notes ? `<div class="meta">${escHtml(day.notes)}</div>` : ''}
      <div class="day-places">${places}</div>
    </div>`;
  }
  panel.innerHTML = html;
}

function handleDayUpdate(data) {
  const dayEl = document.getElementById(`day-${data.date}`);
  if (!dayEl) return;
  const placesEl = dayEl.querySelector('.day-places');
  if (placesEl && data.places) {
    placesEl.innerHTML = data.places.map(p =>
      `<div class="place-item">
        <span>${escHtml(p.name)}</span>
        ${p.estimated_cost ? `<span class="price-tag">$${p.estimated_cost}</span>` : ''}
      </div>`
    ).join('');
  }
}

function handleSearchResults(data) {
  const panel = document.getElementById('plan-panel');
  if (!panel) return;
  const typeLabel = data.type === 'hotels' ? '🏨 Hotels' :
                    data.type === 'flights' ? '✈️ Flights' : '📍 Places';
  let html = `<div class="section-title">${typeLabel}</div>`;
  const results = data.results || {};
  if (data.type === 'hotels' && results.hotels) {
    html += results.hotels.map(h =>
      `<div class="search-result-card">
        <strong>${escHtml(h.name)}</strong>
        ${h.price_range ? `<span class="price-tag"> ${escHtml(h.price_range)}</span>` : ''}
        ${h.rating ? `<div class="meta">⭐ ${escHtml(h.rating)}</div>` : ''}
      </div>`
    ).join('');
  } else if (data.type === 'flights' && results.flights) {
    html += results.flights.map(f =>
      `<div class="search-result-card">
        <strong>${escHtml(f.airline)}</strong>
        ${f.price ? `<span class="price-tag"> ${escHtml(f.price)}</span>` : ''}
      </div>`
    ).join('');
  } else if (data.type === 'places' && results.places) {
    html += results.places.map(p =>
      `<div class="search-result-card">
        <strong>${escHtml(p.name)}</strong>
        ${p.category ? `<div class="meta">${escHtml(p.category)}</div>` : ''}
      </div>`
    ).join('');
  }
  panel.innerHTML = html;
}
