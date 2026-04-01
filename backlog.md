# Backlog

## Error Budget Status: HEALTHY

---

## In Progress

_(없음)_

## Ready (우선순위 순)

### Phase 1: POC
- [ ] #6 - Setup Render deployment (Dockerfile, render.yaml verification) [infra]

### Phase 2: AI Integration
- [ ] #7 - Integrate Gemini API for travel plan generation [feature]
- [ ] #8 - Add web search tool for destination research [feature]
- [ ] #9 - Implement structured output (day-by-day itinerary JSON) [feature]
- [ ] #10 - Write tests for AI-generated travel plans [test]

### Phase 3: Advanced Features
- [ ] #11 - Add Google Calendar integration (read/write events) [feature]
- [ ] #12 - Implement hotel search via web search [feature]
- [ ] #13 - Implement flight search via web search [feature]
- [ ] #14 - Add expense tracking (budget management) [feature]
- [ ] #15 - Build frontend UI [feature]
- [ ] #16 - Write integration tests for advanced features [test]

### Phase 4: Polish
- [ ] #17 - Add comprehensive error handling and validation [improvement]
- [ ] #18 - Performance optimization and caching [improvement]
- [ ] #19 - Write README with architecture overview [docs]
- [ ] #20 - Final test coverage review and gap filling [test]

## Done

- [x] #1 - Initialize FastAPI project structure (main.py, database.py, config.py, /health endpoint) [infra] — 2026-04-01
- [x] #2 - Create travel plan data models (SQLAlchemy ORM + Pydantic schemas) [feature] — 2026-04-01
- [x] #3 - Implement CRUD endpoints for travel plans (POST, GET, PATCH, DELETE + 20 tests) [feature] — 2026-04-01
- [x] #4 - Write unit tests for CRUD endpoints (57 schema unit tests; fixed ExpenseBase.date type shadow bug) [test] — 2026-04-01
- [x] #5 - Add seed data and database initialization (seed.py + scripts/seed_db.py + 20 seed tests) [infra] — 2026-04-01

## Blocked

_(없음)_

---

## Metrics

- Velocity: 1 task/run
- Avg time per task: ~100s
- Total tasks: 20
