# UX 개선: 빠른 응답 + 확인 단계 + 대시보드 상호작용

## 배경

유저 피드백 2가지:
1. 채팅 응답이 느려서 무시당하는 느낌. 한 말풍선 안에서 빠른 첫 응답 → 작업 → 순차 결과를 보여줘야 함.
2. 목적지/일정/예산 안 정했는데 AI가 혼자 계획을 짬. 대시보드 에이전트와 상호작용 불가.

---

## 완료된 작업 (백엔드)

### ✅ Phase 1: Fast Response + Thinking Config (백엔드)
**커밋 대상 파일:**
- `src/app/chat.py`
- `src/app/ai.py`
- `tests/test_ux_fast_response.py` (11 tests)

**구현 내용:**
1. **Fast response**: `process_message()` 시작 시 intent 추출 전에 즉시 `chat_chunk` emit
   - `_build_fast_response(message)` 메서드 추가 (chat.py)
   - 인사/여행/검색 키워드별 즉각 응답 ("네, 알겠습니다! 확인해볼게요 ✨")
   - 위치: `process_message()` 내 coordinator thinking 이전

2. **Progress events**: `_handle_create_plan`에서 `{"type": "progress", "data": {"step": "...", "message": "..."}}` emit
   - `step: "search"` → "📍 {dest} 장소 검색 중..." (작업 시작 시)
   - `step: "places_done"` → "✅ {N}개 장소 발견" (itinerary 생성 완료 후)

3. **Thinking config 최적화** (모든 Gemini 호출):
   - `extract_intent` (chat.py:189): `thinking_level="minimal"` — 단순 분류
   - `_general_with_gemini` (chat.py:3314): `thinking_level="low"` — 빠른 대화
   - `generate_itinerary` (ai.py:82): `thinking_level="medium"`
   - `suggest_improvements` (ai.py:131): `thinking_level="medium"`
   - `refine_itinerary` (ai.py:183): `thinking_level="medium"`

### ✅ Phase 2: Confirm Plan (백엔드)
**커밋 대상 파일:**
- `src/app/chat.py`
- `tests/test_ux_confirm_plan.py` (8 tests)

**구현 내용:**
1. **ChatSession.pending_plan** 필드 추가 (Optional[dict])
2. **Intent에 "confirm_plan" action** 추가 + 추출 프롬프트에 설명 포함
3. **`_general_with_gemini` 변경**: dest+dates+budget 모두 수집 시:
   - 기존: 바로 `_handle_create_plan()` 호출
   - 변경: `session.pending_plan`에 저장 + `{"type": "confirm_plan", "data": {dest, dates, budget}}` emit
4. **`_general_fallback` 변경**: 동일하게 confirm_plan emit
5. **`_handle_confirm_plan()` 핸들러** 추가:
   - `session.pending_plan`에서 조건 꺼내서 `_handle_create_plan` 호출
   - 완료 후 `pending_plan = None`으로 클리어
   - pending 없으면 안내 메시지 응답
6. **Dispatcher에 `confirm_plan` 라우팅** 추가

### ✅ Phase 3: Agent Reasoning (백엔드)
**커밋 대상 파일:**
- `src/app/chat.py`
- `tests/test_ux_agent_reasoning.py` (5 tests)

**구현 내용:**
1. **`agent_reasoning` event**: `{"type": "agent_reasoning", "data": {"agent": "...", "reasoning": "..."}}`
2. 추가 위치:
   - `_handle_create_plan`: planner reasoning (목적지, 기간, 예산, 관심사 포함)
   - `_handle_search_hotels`: hotel_finder reasoning (기간, 1박 예산)
   - `_handle_search_flights`: flight_finder reasoning (출발지→목적지, 날짜)

### ✅ 기존 테스트 수정
- `tests/test_chat.py`: `test_plan_suggestions_emitted_before_chat_chunk` →
  `test_plan_suggestions_emitted_before_handler_chat_chunk`로 변경
  (fast response chat_chunk가 먼저 나오므로 마지막 chat_chunk 기준으로 비교)

**전체 테스트 결과: 1568 passed, 12 skipped, 0 failed**

---

## 남은 작업 (프론트엔드)

### 📋 Task F1: `progress` event → 말풍선 인라인 표시
**파일:** `src/app/static/chat.js`, `src/app/static/index.html`

**현재 상태:**
- `handleSseEvent` switch문에 `progress` case 없음
- 백엔드는 이미 `{"type": "progress", "data": {"step": "search", "message": "📍 도쿄 장소 검색 중..."}}` emit

**구현 방법:**
1. `handleSseEvent`에 `case 'progress':` 추가 (chat.js:326 switch문)
2. `currentStreamBubble`에 progress 텍스트를 `_appendBubbleText`로 이어붙임
3. 기존 chat_chunk와 같은 방식이지만, progress 전용 스타일 적용 가능

```javascript
case 'progress':
  if (currentStreamBubble && event.data && event.data.message) {
    _appendBubbleText(currentStreamBubble, event.data.message + '\n');
    const el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
  }
  break;
```

4. (선택) index.html에 progress 전용 CSS:
```css
.progress-step { color: var(--muted); font-size: 0.9rem; }
```

**기대 결과 (한 말풍선):**
```
네, 알겠습니다! 확인해볼게요 ✨     ← fast response (chat_chunk)
📍 도쿄 장소 검색 중...              ← progress
✅ 12개 장소 발견                    ← progress
도쿄 3일 여행 계획을 생성했습니다.    ← chat_chunk (최종)
```

---

### 📋 Task F2: `confirm_plan` event → 확인 카드 UI
**파일:** `src/app/static/chat.js`, `src/app/static/index.html`

**현재 상태:**
- `handleSseEvent`에 `confirm_plan` case 없음
- 백엔드는 이미 `{"type": "confirm_plan", "data": {"destination": "도쿄", "start_date": "2026-05-01", "end_date": "2026-05-03", "budget": 2000000, "interests": "음식, 문화"}}` emit

**구현 방법:**
1. `handleSseEvent`에 `case 'confirm_plan':` 추가
2. AI 말풍선(currentStreamBubble) 안에 확인 카드 HTML 삽입:

```javascript
case 'confirm_plan':
  if (currentStreamBubble && event.data) {
    const d = event.data;
    const cardHtml = `
      <div class="confirm-plan-card">
        <div class="confirm-plan-summary">
          <div><strong>📍 목적지:</strong> ${d.destination}</div>
          <div><strong>📅 일정:</strong> ${d.start_date} ~ ${d.end_date}</div>
          <div><strong>💰 예산:</strong> ${Number(d.budget).toLocaleString()}원</div>
          ${d.interests ? `<div><strong>🎯 관심사:</strong> ${d.interests}</div>` : ''}
        </div>
        <div class="confirm-plan-actions">
          <button class="confirm-plan-btn confirm-yes" onclick="confirmPlan()">✨ 계획 세우기</button>
          <button class="confirm-plan-btn confirm-edit" onclick="editPlanConditions()">수정하기</button>
        </div>
      </div>`;
    currentStreamBubble.querySelector('.bubble-text').insertAdjacentHTML('beforeend', cardHtml);
    const el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
  }
  break;
```

3. `confirmPlan()` 함수 추가:
```javascript
function confirmPlan() {
  const input = document.getElementById('chat-input');
  input.value = '네, 계획 세워줘';
  sendChatMessage();
}
```

4. `editPlanConditions()` 함수 추가:
```javascript
function editPlanConditions() {
  const input = document.getElementById('chat-input');
  input.focus();
  input.placeholder = '변경하고 싶은 조건을 말씀해주세요...';
}
```

5. index.html에 CSS:
```css
.confirm-plan-card {
  margin-top: 0.8rem;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--card-bg, #fafaf8);
}
.confirm-plan-summary { margin-bottom: 0.8rem; }
.confirm-plan-summary div { margin: 0.3rem 0; font-size: 0.95rem; }
.confirm-plan-actions { display: flex; gap: 0.5rem; }
.confirm-plan-btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
}
.confirm-yes { background: var(--accent, #2c2c2c); color: white; }
.confirm-yes:hover { opacity: 0.85; }
.confirm-edit { background: transparent; border: 1px solid var(--border) !important; }
.confirm-edit:hover { background: var(--hover-bg, #f0f0f0); }
```

---

### 📋 Task F3: `agent_reasoning` event → 에이전트 카드 reasoning 패널
**파일:** `src/app/static/chat.js`, `src/app/static/index.html`

**현재 상태:**
- `handleSseEvent`에 `agent_reasoning` case 없음
- 에이전트 카드 클릭 시 `.agent-detail` 토글만 지원 (검색 결과 표시)
- 백엔드는 이미 `{"type": "agent_reasoning", "data": {"agent": "planner", "reasoning": "도쿄 3일 여행 계획을..."}}` emit

**구현 방법:**
1. 에이전트별 reasoning 로그 저장용 객체:
```javascript
const _agentReasoningLog = {};  // { agent_name: [{reasoning, timestamp}] }
```

2. `handleSseEvent`에 `case 'agent_reasoning':` 추가:
```javascript
case 'agent_reasoning':
  if (event.data && event.data.agent) {
    const agent = event.data.agent;
    if (!_agentReasoningLog[agent]) _agentReasoningLog[agent] = [];
    _agentReasoningLog[agent].push({
      reasoning: event.data.reasoning,
      timestamp: new Date().toLocaleTimeString(),
    });
    _updateAgentReasoningPanel(agent);
  }
  break;
```

3. `_updateAgentReasoningPanel()` 함수:
```javascript
function _updateAgentReasoningPanel(agentName) {
  const el = document.querySelector(`[data-agent="${agentName}"]`);
  if (!el) return;
  let reasoningEl = el.querySelector('.agent-reasoning');
  if (!reasoningEl) {
    reasoningEl = document.createElement('div');
    reasoningEl.className = 'agent-reasoning';
    el.appendChild(reasoningEl);
  }
  const logs = _agentReasoningLog[agentName] || [];
  reasoningEl.innerHTML = logs.map(log =>
    `<div class="reasoning-entry">
       <span class="reasoning-time">${log.timestamp}</span>
       <span class="reasoning-text">${log.reasoning}</span>
     </div>`
  ).join('');
}
```

4. `resetAgentCards()`에 reasoning 초기화 추가:
```javascript
// resetAgentCards 내부에 추가:
Object.keys(_agentReasoningLog).forEach(k => delete _agentReasoningLog[k]);
```

5. 에이전트 카드 클릭 시 reasoning 패널도 토글 (handleAgentStatus done 상태):
   - 기존: `.agent-detail` 토글 (검색 결과)
   - 변경: `.agent-reasoning`과 `.agent-detail` 모두 토글

6. index.html에 CSS:
```css
.agent-reasoning {
  display: none;
  margin-top: 0.5rem;
  padding: 0.5rem;
  font-size: 0.8rem;
  color: var(--muted);
  border-top: 1px solid var(--border);
}
.reasoning-entry { margin: 0.3rem 0; }
.reasoning-time { color: var(--muted); margin-right: 0.5rem; font-size: 0.75rem; }
```

---

### 📋 Task F4: 통합 테스트 (E2E)
**파일:** `e2e/` 디렉토리

**시나리오:**
1. 채팅 입력 → 빠른 응답 말풍선 즉시 표시 확인
2. progress 텍스트가 같은 말풍선에 순차 추가되는지 확인
3. 일반 대화로 조건 수집 → confirm_plan 카드 표시 → "계획 세우기" 클릭 → 계획 생성
4. 에이전트 카드 클릭 → reasoning 로그 표시

---

## SSE Event 전체 목록 (참조)

| Event Type | Data | 출처 | 프론트 처리 상태 |
|-----------|------|------|----------------|
| `chat_chunk` | `{text}` | 모든 handler | ✅ 구현됨 |
| `chat_done` | `{}` | process_message | ✅ 구현됨 |
| `agent_status` | `{agent, status, message, result_count?}` | 모든 handler | ✅ 구현됨 |
| `plan_update` | `{destination, dates, days, budget, ...}` | create_plan | ✅ 구현됨 |
| `day_update` | `{date, places, notes, ...}` | create_plan | ✅ 구현됨 |
| `search_results` | `{type, results}` | search handlers | ✅ 구현됨 |
| `progress` | `{step, message}` | create_plan | ❌ **F1에서 구현** |
| `confirm_plan` | `{destination, start_date, end_date, budget, interests}` | general handler | ❌ **F2에서 구현** |
| `agent_reasoning` | `{agent, reasoning}` | create/search handlers | ❌ **F3에서 구현** |

---

## 아키텍처 참조

### 프론트엔드 핵심 파일
- `src/app/static/chat.js` — SSE 스트림 처리, 말풍선 렌더링, 에이전트 카드 상태
  - `handleSseEvent()` (line ~324): SSE event switch/case dispatcher
  - `handleAgentStatus()` (line ~457): 에이전트 카드 상태 업데이트
  - `_appendBubbleText()`: 말풍선에 텍스트 이어붙이기
  - `currentStreamBubble`: 현재 스트리밍 중인 AI 말풍선 참조
  - `resetAgentCards()` (line ~416): 모든 에이전트 idle로 초기화
- `src/app/static/index.html` — HTML 구조 + CSS
  - 에이전트 카드: `[data-agent="coordinator|planner|place_scout|hotel_finder|flight_finder|budget_analyst|secretary"]`
  - CSS 변수: `--accent`, `--border`, `--muted`, `--card-bg`

### 백엔드 핵심 파일
- `src/app/chat.py` — ChatService (세션, intent 추출, SSE event 생성)
- `src/app/ai.py` — GeminiService (itinerary 생성, 개선 제안)
- `src/app/routers/chat_router.py` — SSE 스트리밍 API endpoint
