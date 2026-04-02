# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready (우선순위 순)

- [ ] #31 - Budget overage alerts (`GET /travel-plans/{id}/expenses/summary` enhancement; add `over_budget: bool` + `overage_pct: float` fields; `GET /travel-plans?over_budget=true` filter; budget warning in plan responses; ~20 tests) [feature]
- [ ] #32 - Plan version history (track changes via lightweight `PlanSnapshot` model; `POST /travel-plans/{id}/snapshot`, `GET /travel-plans/{id}/snapshots`, `GET /travel-plans/{id}/snapshots/{snap_id}` restore preview; ~25 tests) [feature]
- [ ] #33 - Collaborative comments on shared plans (`POST /travel-plans/shared/{token}/comments`; anonymous name + text; `GET /travel-plans/shared/{token}/comments`; `DELETE /travel-plans/{id}/comments/{comment_id}` (owner only); ~25 tests) [feature]

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
- [x] #19 - Write README with architecture overview (component map, data model, API reference, AI pipeline, caching, error handling, full test index) [docs] — 2026-04-02
- [x] #20 - Final test coverage review and gap filling (13 tests for 4 global exception handlers via app.dependency_overrides; 98% → 100% coverage) [test] — 2026-04-02
- [x] #21 - Add manual itinerary editing (DayItineraryUpdate + PlaceUpdate schemas; 8 new endpoints for CRUD on DayItinerary/Place; ownership guards; 51 tests) [feature] — 2026-04-02
- [x] #22 - Plan duplication endpoint (`POST /travel-plans/{id}/duplicate`; copies plan + itineraries + places as new draft; expenses excluded; 21 tests) [feature] — 2026-04-02
- [x] #23 - Place ordering endpoint (`PATCH /plans/{id}/itineraries/{day_id}/places/reorder`; ordered list of place IDs → atomic `order` field update; 24 tests) [feature] — 2026-04-02
- [x] #24 - Travel plan search & filter (`GET /travel-plans?destination=&status=&from=&to=`; destination: case-insensitive ILIKE; status: exact; from/to: start_date range; secondary id DESC sort; 27 tests) [feature] — 2026-04-02
- [x] #25 - Add pagination to GET /travel-plans (`PaginatedPlans` envelope: items/total/page/page_size/pages; `page` ge=1, `page_size` ge=1 le=100 default=20; updated 5 existing test files + 33 new pagination tests) [feature] — 2026-04-02
- [x] #26 - Add notes field to travel plans (`notes: str` on TravelPlan model + PATCH support + `GET /travel-plans?notes=` keyword filter; 23 tests) [feature] — 2026-04-02
- [x] #27 - Plan export endpoint (`GET /travel-plans/{id}/export`; returns full plan JSON with itineraries+places+expenses as `Content-Disposition: attachment` download; 33 tests) [feature] — 2026-04-02
- [x] #28 - Add tags to travel plans (comma-separated `tags` field; PATCH support; `GET /travel-plans?tag=` exact case-insensitive filter using OR conditions; copied on duplicate; included in export; 25 tests) [feature] — 2026-04-02
- [x] #29 - Plan sharing feature (`POST /travel-plans/{id}/share` → generate URLsafe token + set is_shared; `DELETE /travel-plans/{id}/share` → revoke; `GET /travel-plans/shared/{token}` → public read-only view; `is_shared` in TravelPlanOut+Summary; 32 tests; also fixed test_error_handling.py module-level DB issue) [feature] — 2026-04-02
- [x] #30 - AI plan refinement endpoint (`POST /travel-plans/{id}/refine`; RefineRequest.instruction (min=1, max=2000); AI reads current plan + instruction → regenerates itinerary; replaces old DayItinerary/Place; preserves expenses; 503/502 error handling; 30 tests) [feature] — 2026-04-02

## Blocked

_(없음)_

---

## Metrics

- Velocity: 1 task/run
- Avg time per task: ~100s
- Total tasks: 33 planned (30 done, 3 ready)
- Completed: 30/33
- Phase 8 backlog: 3 tasks remaining
