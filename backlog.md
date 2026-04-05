# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready

### Phase 10: Chat + Multi-Agent Dashboard (continued)

- [ ] #87 - Chat frontend: `plan_suggestions` SSE handler — render improvement suggestions panel [feature]
  - ref: markdowns/feat-chat-dashboard.md
  - depends: #86
  - files: src/app/static/chat.js, src/app/static/index.html
  - done: plan_suggestions SSE event renders a collapsible "💡 Suggestions" panel in the dashboard; each suggestion shown as a card; panel auto-expands on new suggestions; 2+ tests
  - gh: #108

- [ ] #88 - Chat: `remove_place` intent — remove a place from a day's itinerary via chat [feature]
  - ref: markdowns/feat-chat-dashboard.md
  - files: src/app/chat.py, tests/test_chat.py
  - done: "1일차 첫 번째 장소 삭제" / "Day 2에서 센소지 빼줘" extracts day_number + place name/index; removes from in-memory plan; emits day_update; planner agent working→done; graceful fallback if no plan; 2+ tests
  - gh: #109

- [ ] #89 - Chat: `add_place` intent — append a custom place to a specific day via chat [feature]
  - ref: markdowns/feat-chat-dashboard.md
  - files: src/app/chat.py, tests/test_chat.py
  - done: "1일차에 서울숲 추가해줘" extracts day_number + place name + optional category; appends to in-memory plan day; emits day_update; place_scout agent working→done; graceful fallback; 2+ tests
  - gh: #110

- [ ] #90 - E2E: suggest_improvements + budget auto-refresh Playwright scenarios [test]
  - ref: markdowns/feat-chat-dashboard.md
  - depends: #85, #86, #87
  - files: e2e/chat.spec.ts
  - done: Playwright scenario "any suggestions?" → suggestions panel appears; place_scout + budget_analyst activate; add_expense → budget bar percentage updates in plan overview; 2+ scenarios pass
  - gh: #111

- [ ] #91 - Chat: `share_plan` intent — generate shareable plan link via chat [feature]
  - ref: markdowns/feat-chat-dashboard.md
  - files: src/app/chat.py, tests/test_chat.py
  - done: "이 계획 공유해줘" → secretary emits plan_shared event with share_url + share_token; frontend shows copiable URL in chat/dashboard; graceful error if no saved plan; 2+ tests
  - gh: #112

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
- [x] #71 - E2E: Chat expense workflow + update_plan Playwright scenarios [test] — 2026-04-05
- [x] #72 - Chat frontend: localStorage session ID persistence [improvement] — 2026-04-05
- [x] #73 - Chat: expense_deleted SSE event + frontend expense row removal [improvement] — 2026-04-05
- [x] #74 - Chat: update_expense intent handler — edit existing expense via chat [feature] — 2026-04-05
- [x] #75 - E2E: SSE reconnect + session state restore Playwright scenarios [test] — 2026-04-05
- [x] #76 - Chat: list_expenses intent — refresh full expense list from DB [feature] — 2026-04-05
- [x] #77 - Chat: copy_plan intent handler — duplicate a saved plan via chat [feature] — 2026-04-05
- [x] #78 - Chat frontend: Expenses panel in dashboard — dedicated expense list section [feature] — 2026-04-05
- [x] #77 - Chat: `copy_plan` intent handler — duplicate a saved plan via chat [feature] — 2026-04-05
- [x] #79 - Chat: `get_weather` intent handler — fetch weather forecast for trip destination [feature] — 2026-04-05
- [x] #80 - E2E: copy_plan + list_expenses + expense panel Playwright scenarios [test] — 2026-04-05
- [x] #81 - Chat: conversation reset — clear history without new session [improvement] — 2026-04-05
- [x] #82 - Chat frontend: Weather forecast panel [feature] — 2026-04-05
- [x] #83 - E2E: weather forecast + conversation reset Playwright scenarios [test] — 2026-04-05
- [x] #84 - Chat: `add_day_note` intent handler — append note to a specific day [feature] — 2026-04-05
- [x] #85 - Chat: budget bar auto-refresh on expense changes [improvement] — 2026-04-05
- [x] #86 - Chat: `suggest_improvements` intent — AI-powered plan improvement suggestions [feature] — 2026-04-05

### Phase 9: User Experience & Polish (remaining, completed)
- [x] #35 - Per-day cost summary (`GET /plans/{id}/itineraries/{day_id}/stats` → place count, total estimated cost, category breakdown dict) [feature] — 2026-04-04
- [x] #36 - Favorite places library (`POST /favorite-places`, `POST /favorite-places/copy-from-itinerary`, `GET /favorite-places`, `GET /favorite-places/{id}`, `DELETE /favorite-places/{id}`; global; copy-from-itinerary support) [feature] — 2026-04-04
- [x] #37 - Plan activity log (`PlanActivity` model; record create/update/delete events on plans with timestamp+action+detail; `GET /travel-plans/{id}/activity`) [feature] — 2026-04-04
- [x] #38 - Bulk expense import via JSON (`POST /plans/{id}/expenses/bulk`; accepts list of ExpenseCreate; atomic — all or nothing; returns BulkExpenseResult{items,count}) [feature] — 2026-04-05

---

## Metrics

- Velocity: 1 task/run
- Total tasks: 86 done, 5 ready (0 in progress)
- Phase: 10 (Chat + Multi-Agent Dashboard)
