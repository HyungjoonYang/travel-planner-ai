# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready (우선순위 순)

### Phase 10: Chat + Multi-Agent Dashboard

> 스펙 문서: `markdowns/feat-chat-dashboard.md`
> 이 목록은 시드 태스크다. evolve가 Architect 단계에서 스펙을 분석하고 추가 태스크를 자율적으로 생성한다.

- [ ] #40 - Chat SSE 스트리밍 엔드포인트 [feature]
  - ref: markdowns/feat-chat-dashboard.md "Phase 1"
  - depends: #39
  - files: src/app/routers/chat.py (new), src/app/main.py (modify)
  - done: POST /chat/sessions, POST /chat/sessions/{id}/messages (SSE), GET/DELETE 세션. 테스트 통과.

- [ ] #41 - ChatService intent 핸들러 연결 (create_plan → GeminiService, search → SearchService) [feature]
  - ref: markdowns/feat-chat-dashboard.md "Phase 1"
  - depends: #39
  - files: src/app/chat.py (modify)
  - done: intent에 따라 기존 서비스를 호출하고 결과를 SSE 이벤트로 emit. 테스트 통과.

### Phase 9: User Experience & Polish (remaining)

- [ ] #35 - Per-day cost summary (`GET /plans/{id}/itineraries/{day_id}/stats` → place count, total estimated cost, category breakdown dict) [feature]
- [ ] #36 - Favorite places library (`POST /favorite-places`, `GET /favorite-places`, `DELETE /favorite-places/{id}`; global across plans; copy a place from itinerary to favorites) [feature]
- [ ] #37 - Plan activity log (`PlanActivity` model; record create/update/delete events on plans with timestamp+action+detail; `GET /travel-plans/{id}/activity`) [feature]
- [ ] #38 - Bulk expense import via JSON (`POST /plans/{id}/expenses/bulk`; accepts list of ExpenseCreate; atomic — all or nothing; returns created list + count) [feature]

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

---

## Metrics

- Velocity: 1 task/run
- Total tasks: 35 done, 6 ready
- Phase: 10 (Chat + Multi-Agent Dashboard)
