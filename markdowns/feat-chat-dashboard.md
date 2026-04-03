# Chat + Live Dashboard UX 리디자인

## Goal
기존 폼 기반 UI → **AI 채팅 + Multi-Agent 실시간 대시보드** 로 전환.
사용자는 왼쪽에서 AI와 대화하고, 오른쪽 대시보드에서 **여행 플래너 팀의 각 에이전트가 일하는 모습**을 실시간으로 본다.

---

## Core Concept: Multi-Agent Dashboard

유저가 메시지를 보내면, 여행 플래너 "회사"의 직원들이 각자 맡은 일을 시작하는 게 보인다.

### 에이전트 (직원) 목록

| Agent | 아이콘 | 역할 | 트리거 |
|-------|--------|------|--------|
| **Coordinator** | 🧠 | 유저 의도 파악, 태스크 분배 | 매 메시지 |
| **Planner** | 📅 | 일정 구성, Day-by-day 스케줄링 | create_plan, modify_day |
| **Place Scout** | 📍 | 장소/맛집/관광지 검색 | create_plan, search_places |
| **Hotel Finder** | 🏨 | 숙소 검색/추천 | search_hotels |
| **Flight Finder** | ✈️ | 항공편 검색 | search_flights |
| **Budget Analyst** | 💰 | 비용 계산, 예산 대비 분석 | 계획 변경 시마다 |
| **Secretary** | 💾 | 저장, 캘린더 내보내기 | save_plan, export_calendar |

### 에이전트 상태

```
idle      → 회색, 조용히 대기
thinking  → 노란 펄스, "분석 중..."
working   → 파란 스피너, "도쿄 맛집 검색 중..."
done      → 초록 체크, "5개 장소 찾음" (결과 요약)
error     → 빨간, "검색 실패 — 재시도 중"
```

---

## UX 시나리오 (Agent View 포함)

### 1단계: 진입

```
┌─ Chat (35%) ──────────────┬─ Agent Dashboard (65%) ─────────────────────┐
│                           │                                              │
│ 🤖 안녕하세요! 어떤 여행을  │  ┌─ Team ──────────────────────────────────┐ │
│    계획하고 계신가요?       │  │ 🧠 Coordinator    ⚪ 대기 중             │ │
│                           │  │ 📅 Planner         ⚪ 대기 중             │ │
│                           │  │ 📍 Place Scout     ⚪ 대기 중             │ │
│                           │  │ 🏨 Hotel Finder    ⚪ 대기 중             │ │
│                           │  │ ✈️ Flight Finder   ⚪ 대기 중             │ │
│                           │  │ 💰 Budget Analyst  ⚪ 대기 중             │ │
│                           │  │ 💾 Secretary       ⚪ 대기 중             │ │
│                           │  └──────────────────────────────────────────┘ │
│                           │                                              │
│                           │  ┌─ Plan ────────────────────────────────────┐│
│                           │  │  아직 계획이 없습니다                       ││
│                           │  └──────────────────────────────────────────┘│
│ [메시지 입력...]    [전송] │                                              │
└───────────────────────────┴──────────────────────────────────────────────┘
```

### 2단계: 유저가 "도쿄 3박4일, 예산 200만원, 맛집 위주" 전송

**실시간 Agent 활동 (순서대로 애니메이션):**

```
🧠 Coordinator    🟡 "요청 분석 중..."              ← 0.0s
🧠 Coordinator    🟢 "도쿄 3박4일, 맛집 여행 파악"    ← 0.5s
📅 Planner        🟡 "일정 구성 준비 중..."           ← 0.5s (Coordinator가 넘김)
📍 Place Scout    🔵 "도쿄 맛집/관광지 검색 중..."     ← 0.6s (동시 시작)
💰 Budget Analyst 🔵 "200만원 예산 배분 계산 중..."    ← 0.6s (동시 시작)
📍 Place Scout    🟢 "12개 장소 찾음"                ← 2.0s
📅 Planner        🔵 "4일 일정 배치 중..."            ← 2.1s (Scout 결과 받고 시작)
💰 Budget Analyst 🟢 "항공 45만, 숙소 36만, ..."     ← 2.5s
📅 Planner        🟢 "4일 일정 완성!"                ← 3.5s
```

**동시에 Plan 영역이 채워짐:**

```
┌─ Team ───────────────────────────────────────┐
│ 🧠 Coordinator    🟢 도쿄 3박4일, 맛집 여행    │
│ 📅 Planner        🔵 Day 3/4 배치 중...       │  ← 스피너
│ 📍 Place Scout    🟢 12개 장소 찾음 ▾          │  ← 클릭하면 펼침
│ 💰 Budget Analyst 🟢 예산 배분 완료 ▾          │
│ 🏨 Hotel Finder   ⚪ 대기 중                  │
│ ✈️ Flight Finder  ⚪ 대기 중                  │
│ 💾 Secretary      ⚪ 대기 중                  │
└──────────────────────────────────────────────┘

┌─ Plan ───────────────────────────────────────┐
│ 🗼 도쿄  ·  5/1~5/4  ·  200만원              │
│                                              │
│ Day 1 ✅ 아사쿠사                             │
│ ├ 센소지 (문화) — ¥0                          │
│ ├ 아메요코 시장 (맛집) — ¥2,000               │
│ └ 스카이트리 (관광) — ¥2,100                  │
│                                              │
│ Day 2 ✅ 시부야·하라주쿠                       │
│ ├ ...                                        │
│                                              │
│ Day 3 ⏳ 생성 중...                           │  ← 스켈레톤
│ Day 4 ⏳ 생성 중...                           │
│                                              │
│ ████████░░░░ 68% 예산 사용 (136만/200만)      │
└──────────────────────────────────────────────┘
```

### 3단계: "호텔도 추천해줘, 시부야 근처 15만원 이하"

```
🧠 Coordinator    🟡 "호텔 검색 요청 파악"
🧠 Coordinator    🟢 → Hotel Finder에 전달
🏨 Hotel Finder   🔵 "시부야 근처, ¥15,000 이하 검색 중..."
🏨 Hotel Finder   🟢 "5개 호텔 찾음" ▾
                     ├ 시부야 그랜벨 ¥11,000/박 ★4.2
                     ├ 도큐 스테이 ¥9,800/박 ★4.0
                     └ ...
💰 Budget Analyst 🔵 "숙소 비용 재계산 중..."
💰 Budget Analyst 🟢 "숙소 33만원 → 총 169만원 (84%)"
```

### 4단계: "이 계획 저장해줘"

```
🧠 Coordinator    🟢 → Secretary에 전달
💾 Secretary      🔵 "여행 계획 저장 중..."
💾 Secretary      🟢 "저장 완료! Plan #7"
```

---

## Architecture

### SSE 이벤트 타입 (확장)

기존 이벤트에 agent 이벤트 추가:

```
agent_status   → 에이전트 상태 변경 (핵심 — 대시보드 애니메이션 드라이버)
                 {agent: "place_scout", status: "working", message: "도쿄 맛집 검색 중..."}
                 {agent: "place_scout", status: "done", message: "12개 장소 찾음", result_count: 12}

chat_chunk     → AI 응답 텍스트 스트리밍
chat_done      → AI 응답 완료
plan_update    → Plan 영역 전체 갱신
day_update     → 특정 Day 카드 갱신
search_results → 에이전트 결과 상세 (펼쳐서 보기)
plan_saved     → 저장 확인
error          → 에러
```

### Backend: ChatService가 agent_status 이벤트를 emit

```python
async def process_message(self, session_id, user_message):
    # 1. Coordinator 시작
    yield {"type": "agent_status", "data": {"agent": "coordinator", "status": "thinking", "message": "요청 분석 중..."}}
    
    intent = await self._extract_intent(user_message)
    
    yield {"type": "agent_status", "data": {"agent": "coordinator", "status": "done", "message": f"{intent.action} 파악"}}
    
    # 2. Intent에 따라 에이전트 활성화
    if intent.action == "create_plan":
        yield {"type": "agent_status", "data": {"agent": "place_scout", "status": "working", "message": f"{dest} 장소 검색 중..."}}
        yield {"type": "agent_status", "data": {"agent": "budget_analyst", "status": "working", "message": "예산 배분 계산 중..."}}
        
        places = await self._search_places(...)
        yield {"type": "agent_status", "data": {"agent": "place_scout", "status": "done", "message": f"{len(places)}개 장소 찾음"}}
        
        yield {"type": "agent_status", "data": {"agent": "planner", "status": "working", "message": "일정 배치 중..."}}
        # ... Day별로 plan_update/day_update 이벤트 emit
```

### Frontend: Agent Panel 렌더링

```javascript
const AGENTS = [
  {id: 'coordinator',    icon: '🧠', name: 'Coordinator',    role: '총괄'},
  {id: 'planner',        icon: '📅', name: 'Planner',        role: '일정 구성'},
  {id: 'place_scout',    icon: '📍', name: 'Place Scout',    role: '장소 검색'},
  {id: 'hotel_finder',   icon: '🏨', name: 'Hotel Finder',   role: '숙소 검색'},
  {id: 'flight_finder',  icon: '✈️', name: 'Flight Finder',  role: '항공편 검색'},
  {id: 'budget_analyst', icon: '💰', name: 'Budget Analyst',  role: '비용 분석'},
  {id: 'secretary',      icon: '💾', name: 'Secretary',       role: '저장/내보내기'},
];

function handleAgentStatus(data) {
  const el = document.querySelector(`[data-agent="${data.agent}"]`);
  el.className = `agent-card agent-${data.status}`;  // idle|thinking|working|done|error
  el.querySelector('.agent-message').textContent = data.message;
  if (data.status === 'done' && data.result_count) {
    el.querySelector('.agent-detail').classList.remove('hidden');  // 펼치기 가능
  }
}
```

---

## Dashboard Layout (최종)

```
┌─ Chat (35%) ────────┬─ Dashboard (65%) ──────────────────────────────┐
│                     │                                                │
│  채팅 영역           │  ┌─ 🏢 Team Activity ─────────────────────┐   │
│                     │  │ (에이전트 카드 7개, 실시간 상태)          │   │
│                     │  │ 접기/펼치기 가능                         │   │
│                     │  └─────────────────────────────────────────┘   │
│                     │                                                │
│                     │  ┌─ ✈️ Travel Plan ────────────────────────┐   │
│                     │  │ Overview (목적지, 날짜, 예산바)           │   │
│                     │  │ Day 1, Day 2, Day 3, Day 4 카드         │   │
│                     │  │ Budget Tracker                          │   │
│                     │  │ Hotels / Flights (검색 결과)             │   │
│                     │  └─────────────────────────────────────────┘   │
│                     │                                                │
│ [입력]       [전송] │                                                │
└─────────────────────┴────────────────────────────────────────────────┘
```

**Team Activity 패널**은 대시보드 상단에 고정. 아무도 안 일하고 있으면 compact 모드(한 줄 요약). 에이전트가 활성화되면 자동으로 펼쳐지며 실시간 진행 표시.

---

## Files to Change

### 새 파일
| File | Lines (est.) | 역할 |
|------|-------------|------|
| `src/app/chat.py` | ~250 | ChatService + agent_status 이벤트 emit |
| `src/app/routers/chat.py` | ~80 | SSE 스트리밍 엔드포인트, 세션 CRUD |
| `src/app/static/chat.js` | ~500 | 채팅 UI, SSE 파싱, Agent 패널, 대시보드 렌더링 |

### 수정 파일
| File | 변경량 | 내용 |
|------|--------|------|
| `src/app/main.py` | +3줄 | chat router 등록, chat.js 로딩 |
| `src/app/schemas.py` | +15줄 | ChatMessageRequest, ChatSessionOut, AgentStatusEvent |
| `src/app/ai.py` | +5줄 | generate_itinerary_async 래퍼 |
| `src/app/static/index.html` | +50줄 CSS, +10줄 JS | Agent 카드 스타일, 애니메이션, chat 페이지 라우팅 |

### 안 건드리는 파일
- models.py, database.py, config.py
- routers/travel_plans.py, expenses.py, search.py, calendar.py, ai_plans.py
- web_search.py, hotel_search.py, flight_search.py, cache.py

---

## Implementation Order

### Phase 1: Backend (chat.py + router)
1. `src/app/chat.py` — ChatService 구현
   - system prompt (한/영 대응, intent 추출)
   - **agent_status 이벤트 emit** 로직 (각 단계마다)
   - intent별 핸들러 (create_plan, modify_day, search_*, save_plan)
   - 기존 서비스 재사용
2. `src/app/routers/chat.py` — SSE 엔드포인트
3. `src/app/main.py` — 라우터 등록
4. 테스트 작성

### Phase 2: Frontend
5. `src/app/static/index.html` — CSS (split-pane, agent 카드, 상태 애니메이션)
6. `src/app/static/chat.js`
   - Agent Panel 렌더링 + 상태 트랜지션 애니메이션
   - 채팅 UI (메시지 버블, SSE 스트리밍)
   - Plan 대시보드 (Overview, Day cards, Budget, Search results)
7. 네비게이션 연결 (chat을 기본 페이지로)

### Phase 3: Polish
8. Agent 카드 compact/expanded 토글
9. 에이전트 결과 펼쳐보기 (Place Scout → 장소 목록, Hotel Finder → 호텔 목록)
10. 모바일 반응형
11. 테스트 추가 (E2E 포함)

---

## Agent Status Animation CSS

```css
.agent-card { transition: all 0.3s; padding: .5rem .75rem; border-radius: 6px; display: flex; align-items: center; gap: .75rem; }

.agent-idle     { opacity: 0.5; }
.agent-thinking { background: #fff8e1; animation: pulse 1.5s infinite; }
.agent-working  { background: #e3f2fd; }
.agent-working .agent-spinner { display: inline-block; animation: spin 1s linear infinite; }
.agent-done     { background: #e8f5e9; }
.agent-error    { background: #ffebee; }

@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
@keyframes spin  { to { transform: rotate(360deg); } }
```

---

## Risks

| 리스크 | 대응 |
|--------|------|
| Gemini 일정 생성 느림 (3~5초) | agent_status 애니메이션이 대기 시간을 흥미롭게 만듦 |
| Intent 추출 실패 | Coordinator가 "확인 질문" 상태로 폴백 |
| 에이전트 상태 순서 꼬임 | 각 에이전트에 monotonic sequence 부여 |
| SSE 끊김 | reconnect + 마지막 상태 복원 |

---

## Test Cases

```
tests/test_chat.py
  test_create_session
  test_send_message_returns_sse_stream
  test_agent_status_events_emitted
  test_coordinator_always_first_agent
  test_place_scout_activated_on_create_plan
  test_hotel_finder_activated_on_search_hotels
  test_budget_analyst_updates_after_plan_change
  test_intent_extraction_create_plan
  test_intent_extraction_modify_day
  test_intent_extraction_save_plan
  test_session_expiry_after_ttl
  test_plan_save_persists_to_db
  test_error_agent_status_on_gemini_failure

e2e/chat.spec.ts
  test_chat_page_loads_with_agent_panel
  test_agents_idle_on_load
  test_agents_activate_on_message
  test_plan_builds_in_dashboard
  test_agent_done_shows_result_count
```
