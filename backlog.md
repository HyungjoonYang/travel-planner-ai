# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready (우선순위 순)

### Phase 4: Polish
- [ ] #19 - Write README with architecture overview [docs]
- [ ] #20 - Final test coverage review and gap filling [test]

## Done

- [x] #1 - Initialize FastAPI project structure (main.py, database.py, config.py, /health endpoint) [infra] — 2026-04-01
- [x] #2 - Create travel plan data models (SQLAlchemy ORM + Pydantic schemas) [feature] — 2026-04-01
- [x] #3 - Implement CRUD endpoints for travel plans (POST, GET, PATCH, DELETE + 20 tests) [feature] — 2026-04-01
- [x] #4 - Write unit tests for CRUD endpoints (57 schema unit tests; fixed ExpenseBase.date type shadow bug) [test] — 2026-04-01
- [x] #5 - Add seed data and database initialization (seed.py + scripts/seed_db.py + 20 seed tests) [infra] — 2026-04-01
- [x] #6 - Setup Render deployment (Dockerfile, render.yaml verification, 27 deployment tests) [infra] — 2026-04-01
- [x] #7 - Integrate Gemini API for travel plan generation (GeminiService + POST /ai/generate + 31 tests) [feature] — 2026-04-01
- [x] #8 - Add web search tool for destination research (WebSearchService + GET /search/places + 35 tests) [feature] — 2026-04-01
- [x] #9 - Implement structured output (response_schema=AIItineraryResult + POST /ai/preview + 25 tests) [feature] — 2026-04-01
- [x] #10 - Write tests for AI-generated travel plans (42 tests: Pydantic models, multi-day persistence, invalid date handling, place order, budget validation, interests edge cases) [test] — 2026-04-01
- [x] #11 - Add Google Calendar integration (CalendarService + POST /plans/{id}/calendar/export + 40 tests) [feature] — 2026-04-01
- [x] #12 - Implement hotel search via web search (HotelSearchService + GET /search/hotels + 44 tests) [feature] — 2026-04-01
- [x] #13 - Implement flight search via web search (FlightSearchService + GET /search/flights + 50 tests) [feature] — 2026-04-01
- [x] #14 - Add expense tracking (ExpensesRouter + CRUD + GET /plans/{id}/expenses/summary + 57 tests) [feature] — 2026-04-01
- [x] #15 - Build frontend UI (vanilla JS SPA served via FastAPI StaticFiles; plans CRUD, AI generation, expense tracking, hotel/flight/destination search; 10 tests) [feature] — 2026-04-01
- [x] #16 - Write integration tests for advanced features (39 tests: plan lifecycle, expense isolation, budget summary, AI generation+persistence, calendar export, search error propagation, multi-plan independence) [test] — 2026-04-01
- [x] #17 - Add comprehensive error handling and validation (cross-field date validation, global SQLAlchemy exception handlers, request ID middleware, structured logging, 24 tests) [improvement] — 2026-04-01
- [x] #18 - Performance optimization and caching (TTLCache + search endpoint caching + GET /cache/stats + DELETE /cache + 35 tests) [improvement] — 2026-04-01

## Blocked

_(없음)_

---

## Metrics

- Velocity: 1 task/run
- Avg time per task: ~100s
- Total tasks: 20
- Completed: 18/20
