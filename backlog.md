# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready

### Phase 10: Chat + Multi-Agent Dashboard (continued)

- [ ] #71 - E2E: Chat expense workflow + update_plan Playwright scenarios [test]
  - ref: markdowns/feat-chat-dashboard.md (e2e test cases)
  - files: e2e/chat.spec.ts
  - done: SSE-mocked scenario for `expense_added` event renders expense row in plan panel; `expense_summary` event renders budget breakdown; `plan_update` after `update_plan` reflects new metadata (destination/dates); 3+ new test scenarios added
  - gh: #67

- [ ] #72 - Chat frontend: localStorage session ID persistence [improvement]
  - ref: markdowns/feat-chat-dashboard.md (SSE reconnect + session state restore)
  - files: src/app/static/chat.js
  - done: chatSessionId written to localStorage on creation; initChatSession() checks localStorage first (GET verify), falls back to new session if expired/missing; tests cover happy-path + expired fallback
  - gh: #73

- [ ] #73 - Chat: expense_deleted SSE event + frontend expense row removal [improvement]
  - ref: markdowns/feat-chat-dashboard.md (expense section in plan panel)
  - files: src/app/chat.py, src/app/static/chat.js, tests/test_chat_dashboard.py
  - done: _handle_delete_expense emits {type: "expense_deleted", data: {name, budget_summary}}; chat.js handleExpenseDeleted removes matching row from .expense-list; budget bar updates; 2+ new tests
  - gh: #74

- [ ] #74 - Chat: update_expense intent handler — edit existing expense via chat [feature]
  - ref: markdowns/feat-chat-dashboard.md (expense management via chat)
  - files: src/app/chat.py, tests/test_chat.py
  - done: update_expense added to Intent.action + system prompt; _handle_update_expense finds by name and updates amount/category; emits expense_updated + expense_summary events; chat.js handles expense_updated; 2+ tests
  - gh: #75

- [ ] #75 - E2E: SSE reconnect + session state restore Playwright scenarios [test]
  - ref: markdowns/feat-chat-dashboard.md (SSE reconnect, session restore)
  - depends: #70
  - files: e2e/chat.spec.ts
  - done: test 1 mocks GET /chat/sessions/{id} returning last_plan+agent_states, verifies plan panel + agent cards restored; test 2 mocks message_history, verifies chat bubbles rendered; both use route mocking
  - gh: #76

- [ ] #76 - Chat: list_expenses intent — refresh full expense list from DB [feature]
  - ref: markdowns/feat-chat-dashboard.md (expense management); CLAUDE.md User Story 5
  - files: src/app/chat.py, src/app/static/chat.js, tests/test_chat.py
  - done: list_expenses added to Intent.action + system prompt; _handle_list_expenses queries all expenses for saved plan; emits expense_list event; chat.js handleExpenseList clears+re-renders .expense-list; 2+ tests
  - gh: #77

## Blocked

_(없음)_

---

## Done

### Phase 1: POC
- [x] #1 - Initialize FastAPI project structure [infra] — 2026-04-01
- [x] #2 - Create travel plan data models [feature] — 2026-04-01
- [x] #3 - Implement CRUD endpoints [feature] — 2026-04-01
- [x] #4 - Write unit tests for CRUD [test] — 2026-04-01
- [x] #5 - Add seed data and database initialization [infra] — 2026-04-01
- [x] #6 - Setup Render deployment [infra] — 2026-04-01

### Phase 2: AI Integration
- [x] #7 - Integrate Gemini API [feature] — 2026-04-01
- [x] #8 - Add web search tool [feature] — 2026-04-01
- [x] #9 - Implement structured output [feature] — 2026-04-01
- [x] #10 - Write tests for AI-generated plans [test] — 2026-04-01

### Phase 3: Advanced Features
- [x] #11 - Add Google Calendar integration [feature] — 2026-04-01
- [x] #12 - Implement hotel search [feature] — 2026-04-01
- [x] #13 - Implement flight search [feature] — 2026-04-01
- [x] #14 - Add expense tracking [feature] — 2026-04-01
- [x] #15 - Build frontend UI [feature] — 2026-04-01
- [x] #16 - Write integration tests [test] — 2026-04-01

### Phase 4: Polish
- [x] #17 - Add comprehensive error handling [improvement] — 2026-04-01
- [x] #18 - Performance optimization and caching [improvement] — 2026-04-01

### Phase 5~8 (evolve auto-generated)
- [x] #19 - README with architecture overview [docs] — 2026-04-02
- [x] #20 - Final test coverage review (100%) [test] — 2026-04-02
- [x] #21 - Manual itinerary editing [feature] — 2026-04-02
- [x] #22 - Plan duplication [feature] — 2026-04-02
- [x] #23 - Place ordering [feature] — 2026-04-02
- [x] #24 - Travel plan search & filter [feature] — 2026-04-02
- [x] #25 - Pagination [feature] — 2026-04-02
- [x] #26 - Notes field [feature] — 2026-04-02
- [x] #27 - Plan export [feature] — 2026-04-02
- [x] #28 - Tags [feature] — 2026-04-02
- [x] #29 - Plan sharing [feature] — 2026-04-02
- [x] #30 - AI plan refinement [feature] — 2026-04-02
- [x] #31 - Budget overage alerts [feature] — 2026-04-02
- [x] #32 - Plan version history [feature] — 2026-04-02
- [x] #33 - Collaborative comments [feature] — 2026-04-02
- [x] #34 - Place ratings and reviews [feature] — 2026-04-02

### Phase 10: Chat + Multi-Agent Dashboard
- [x] #39 - ChatService 기본 구조 (ConversationState, intent 추출, 세션 관리) [feature] — 2026-04-03
- [x] #40 - Chat SSE 스트리밍 엔드포인트 (POST /chat/sessions, SSE messages, GET/DELETE) [feature] — 2026-04-04
- [x] #41 - ChatService intent 핸들러 연결 (create_plan → GeminiService, search → SearchService) [feature] — 2026-04-04
- [x] #42 - Chat page HTML/CSS: nav tab + 35/65 split-pane + 7 agent cards (idle state) in index.html [feature] — 2026-04-04
- [x] #43 - chat.js: SSE client + chat message UI + agent_status event handler [feature] — 2026-04-04
- [x] #44 - chat.js: Plan dashboard rendering (plan_update / day_update / search_results SSE events) [feature] — 2026-04-04
- [x] #45 - Agent panel compact/expanded toggle + mobile responsive layout [feature] — 2026-04-04
- [x] #46 - SSE reconnect with exponential backoff + session state restore on reconnect [feature] — 2026-04-04
- [x] #47 - modify_day intent handler: update a day's places via chat [feature] — 2026-04-04
- [x] #48 - Secretary save_plan handler: persist plan to DB [feature] — 2026-04-04
- [x] #49 - E2E Playwright tests for chat page [test] — 2026-04-04
- [x] #50 - Budget Analyst: real per-category cost breakdown in chat [feature] — 2026-04-04
- [x] #51 - Reporter agent: auto-close GitHub Issues on task completion [infra] — 2026-04-04
- [x] #52 - Chat Secretary: export_calendar intent handler [feature] — 2026-04-04
- [x] #53 - Chat conversation context: pass last 10 messages to Gemini [improvement] — 2026-04-04
- [x] #56 - Chat: list_plans intent handler — show saved plans in chat [feature] — 2026-04-04
- [x] #54 - Coordinator agent: gh issue comment on task assignment [infra] — 2026-04-04
- [x] #55 - Incident auto-issue: create Bug GitHub Issue on 3 consecutive QA failures [infra] — 2026-04-04
- [x] #57 - Chat frontend: plans_list SSE event handler — render saved plan cards in dashboard [feature] — 2026-04-04
- [x] #58 - Chat frontend: `calendar_exported` SSE event handler — show export confirmation [feature] — 2026-04-04
- [x] #59 - Chat: `delete_plan` intent handler — delete a saved plan via chat [feature] — 2026-04-04
- [x] #60 - Chat: `view_plan` intent handler — load saved plan into dashboard by name/ID [feature] — 2026-04-04
- [x] #61 - Reporter: weekly Discussion summary — auto-post Phase progress as GitHub Discussion [infra] — 2026-04-04
- [x] #62 - Chat dashboard: Hotels & Flights dedicated result sections [feature] — 2026-04-05
- [x] #63 - Chat: `add_expense` intent handler + `expense_added` SSE frontend [feature] — 2026-04-05
- [x] #64 - Chat: `update_plan` intent handler — edit plan metadata via chat [feature] — 2026-04-05
- [x] #65 - Chat: `get_expense_summary` intent — expense breakdown via chat [feature] — 2026-04-05
- [x] #66 - Chat session: persist conversation history to SQLite [improvement] — 2026-04-05
- [x] #67 - Chat: `refine_plan` intent handler — AI plan refinement via chat [feature] — 2026-04-05
- [x] #68 - Chat: `delete_expense` intent handler [feature] — 2026-04-05
- [x] #69 - Chat dashboard: Place Scout results dedicated persistent section [improvement] — 2026-04-05
- [x] #70 - Chat: restore message bubbles from DB after SSE reconnect [improvement] — 2026-04-05

### Phase 9: User Experience & Polish (remaining, completed)
- [x] #35 - Per-day cost summary (`GET /plans/{id}/itineraries/{day_id}/stats` → place count, total estimated cost, category breakdown dict) [feature] — 2026-04-04
- [x] #36 - Favorite places library (`POST /favorite-places`, `POST /favorite-places/copy-from-itinerary`, `GET /favorite-places`, `GET /favorite-places/{id}`, `DELETE /favorite-places/{id}`; global; copy-from-itinerary support) [feature] — 2026-04-04
- [x] #37 - Plan activity log (`PlanActivity` model; record create/update/delete events on plans with timestamp+action+detail; `GET /travel-plans/{id}/activity`) [feature] — 2026-04-04
- [x] #38 - Bulk expense import via JSON (`POST /plans/{id}/expenses/bulk`; accepts list of ExpenseCreate; atomic — all or nothing; returns BulkExpenseResult{items,count}) [feature] — 2026-04-05

---

## Metrics

- Velocity: 1 task/run
- Total tasks: 70 done, 6 ready (0 in progress)
- Phase: 10 (Chat + Multi-Agent Dashboard)
