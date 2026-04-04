# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready (우선순위 순)

### Phase 10: Chat + Multi-Agent Dashboard (continued)

- [ ] #50 - Budget Analyst: real per-category cost breakdown in chat [feature]
  - ref: markdowns/feat-chat-dashboard.md (Stage 2 — Budget Analyst)
  - depends: #46
  - files: src/app/chat.py, src/app/static/chat.js, tests/test_chat.py, tests/test_frontend.py
  - done: search_results event type=budget emitted with {accommodation,transport,food,activities,total}; agent detail renders breakdown; 2 tests pass
  - gh: #26

- [ ] #51 - Reporter agent: auto-close GitHub Issues on task completion [infra]
  - ref: markdowns/feat-dynamic-repo.md (Phase 1 — Reporter issue close)
  - files: .claude/agents/reporter.md
  - done: reporter.md includes step to `gh issue close <number>` and `Closes #<number>` in PR body
  - gh: #27

### Phase 9: User Experience & Polish (remaining)
- [ ] #38 - Bulk expense import via JSON (`POST /plans/{id}/expenses/bulk`; accepts list of ExpenseCreate; atomic — all or nothing; returns created list + count) [feature]
  - gh: #8

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

### Phase 9: User Experience & Polish (remaining, completed)
- [x] #35 - Per-day cost summary (`GET /plans/{id}/itineraries/{day_id}/stats` → place count, total estimated cost, category breakdown dict) [feature] — 2026-04-04
- [x] #36 - Favorite places library (`POST /favorite-places`, `POST /favorite-places/copy-from-itinerary`, `GET /favorite-places`, `GET /favorite-places/{id}`, `DELETE /favorite-places/{id}`; global; copy-from-itinerary support) [feature] — 2026-04-04
- [x] #37 - Plan activity log (`PlanActivity` model; record create/update/delete events on plans with timestamp+action+detail; `GET /travel-plans/{id}/activity`) [feature] — 2026-04-04

---

## Metrics

- Velocity: 1 task/run
- Total tasks: 48 done, 3 ready
- Phase: 10 (Chat + Multi-Agent Dashboard)
