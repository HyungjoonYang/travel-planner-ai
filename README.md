# Travel Planner AI

> A self-evolving AI travel planner — built entirely by autonomous AI agents.

## What is this?

This repository is an experiment in **AI-native software development**. A human wrote only the initial configuration (`CLAUDE.md`, workflows, backlog). Everything else — code, tests, bug fixes, deployment — is done autonomously by an AI agent running on a cron schedule.

**Zero human code contributions.** Check the git log.

---

## How the Agent Works

```
┌─────────────────────────────────────────────────────┐
│                  GitHub Actions Cron                  │
│              KST 22:00~06:00, every 30min             │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                   Claude Code CLI                     │
│                                                       │
│  1. Health Check (run all tests)                      │
│  2. Read status.md + error-budget.json                │
│  3. Pick next task from backlog.md                    │
│  4. Implement code + write tests                      │
│  5. Record LTES metrics                               │
│  6. Update status.md, backlog.md, dashboards          │
│  7. Commit & push to main                             │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                  Render Auto-Deploy                    │
│              Push to main → live in ~60s              │
└─────────────────────────────────────────────────────┘
```

The agent follows an **Evolve Loop**: health-check → plan → build → test → record → commit. Every decision is logged with LTES metrics (Latency, Traffic, Errors, Saturation — Google SRE's Four Golden Signals).

---

## Application Features

| Feature | Description |
|---------|-------------|
| Travel Plan CRUD | Create, read, update, delete travel plans with destination, dates, budget, interests |
| AI Itinerary Generation | Gemini AI generates day-by-day plans with real places, costs, and reasoning |
| Place Search | AI-powered destination research via Gemini Google Search grounding |
| Hotel Search | AI-powered hotel recommendations with dates, budget, and guest count filters |
| Flight Search | AI-powered flight search between any two cities |
| Expense Tracking | Per-plan expense CRUD with budget vs. spend summary by category |
| Google Calendar Export | Push confirmed itinerary days to Google Calendar via OAuth 2.0 |
| Frontend UI | Vanilla JS SPA served from FastAPI — no build step required |
| Search Caching | 5-minute TTL in-memory cache on all search endpoints |
| Observability | Request IDs, structured logging, global error handlers |

---

## Architecture

### Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | FastAPI + Uvicorn | Async, fast, auto-docs via OpenAPI |
| Database | SQLite + SQLAlchemy 2.0 | Zero-config, file-based, type-safe ORM |
| Validation | Pydantic v2 | Native FastAPI integration, strict typing |
| AI | Google Gemini API (`google-genai`) | Structured JSON output + Google Search grounding in one API |
| Frontend | Vanilla JS SPA | No build toolchain, served directly from FastAPI |
| Deployment | Render (render.yaml) | Auto-deploy on push, free tier |
| CI/CD | GitHub Actions (cron) | Autonomous agent runs every 30 min overnight |

### Component Map

```
src/app/
├── main.py                  # FastAPI app, middleware, global error handlers, cache admin
├── config.py                # Settings from environment variables
├── database.py              # SQLAlchemy engine, session factory, Base
├── models.py                # ORM models (TravelPlan, DayItinerary, Place, Expense)
├── schemas.py               # Pydantic request/response schemas
├── ai.py                    # GeminiService — structured itinerary generation
├── web_search.py            # WebSearchService — place search via Gemini grounding
├── hotel_search.py          # HotelSearchService — hotel search via Gemini grounding
├── flight_search.py         # FlightSearchService — flight search via Gemini grounding
├── calendar_service.py      # CalendarService — Google Calendar export via REST
├── cache.py                 # TTLCache — thread-safe in-memory cache with expiry
├── seed.py                  # Demo seed data for development
├── static/index.html        # Single-page frontend app
└── routers/
    ├── travel_plans.py      # CRUD /travel-plans
    ├── expenses.py          # CRUD /plans/{id}/expenses + /summary
    ├── ai_plans.py          # POST /ai/generate, POST /ai/preview
    ├── search.py            # GET /search/places, /hotels, /flights
    └── calendar.py          # POST /plans/{id}/calendar/export
```

### Data Model

```
TravelPlan
├── id, destination, start_date, end_date
├── budget (float), interests (comma-separated), status (draft|confirmed)
├── created_at, updated_at
├── itineraries → [DayItinerary]
│   ├── date, notes, transport
│   └── places → [Place]
│       ├── name, category, address
│       ├── estimated_cost, ai_reason, order
└── expenses → [Expense]
    ├── name, amount, category
    └── date, notes
```

### AI Pipeline

```
User Request (destination, dates, budget, interests)
         │
         ▼
GeminiService.generate_itinerary()
         │  ── system prompt with few-shot examples
         │  ── response_schema → AIItineraryResult (Pydantic)
         ▼
Structured JSON: { days: [ { date, places: [...], notes, transport } ] }
         │
         ▼
Persist to DB as TravelPlan + DayItinerary + Place rows
```

For search endpoints (places/hotels/flights), Gemini is called with the `google_search` grounding tool — it fetches live results from the web and returns structured data without any separate search API key.

### Caching

All three search endpoints (`/search/places`, `/search/hotels`, `/search/flights`) share a **TTLCache** instance (5-minute TTL):

- Cache key = lowercase(destination + filter params)
- Cache hit → returns stored result immediately, skips Gemini API call
- Errors are never cached
- Admin endpoints: `GET /cache/stats`, `DELETE /cache`

### Error Handling

| Scenario | HTTP Status | Handler |
|----------|-------------|---------|
| DB constraint violation | 409 | `IntegrityError` handler in `main.py` |
| DB unreachable | 503 | `OperationalError` handler |
| Any other DB error | 500 | `SQLAlchemyError` handler |
| Gemini API unavailable | 503 | Router-level `ValueError` catch |
| Gemini API call fails | 502 | Router-level `Exception` catch |
| Resource not found | 404 | Explicit `HTTPException` in each router |
| Invalid request body | 422 | Pydantic automatic validation |

Every response includes an `X-Request-ID` header (auto-generated UUID or echoed from request).

---

## API Reference

### Travel Plans

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/travel-plans` | Create a travel plan |
| `GET` | `/travel-plans` | List all plans (summary) |
| `GET` | `/travel-plans/{id}` | Get plan with full itinerary |
| `PATCH` | `/travel-plans/{id}` | Partial update |
| `DELETE` | `/travel-plans/{id}` | Delete plan and all children |

### AI Generation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ai/generate` | Generate + persist AI itinerary |
| `POST` | `/ai/preview` | Generate AI itinerary without saving |

### Search

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/search/places?destination=…` | Search places (AI + web grounding) |
| `GET` | `/search/hotels?destination=…` | Search hotels (AI + web grounding) |
| `GET` | `/search/flights?departure_city=…&arrival_city=…` | Search flights (AI + web grounding) |

### Expenses

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/plans/{id}/expenses` | Add expense to plan |
| `GET` | `/plans/{id}/expenses` | List expenses |
| `GET` | `/plans/{id}/expenses/summary` | Budget vs. spend by category |
| `GET` | `/plans/{id}/expenses/{eid}` | Get single expense |
| `PATCH` | `/plans/{id}/expenses/{eid}` | Update expense |
| `DELETE` | `/plans/{id}/expenses/{eid}` | Delete expense |

### Calendar

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/plans/{id}/calendar/export` | Export itinerary to Google Calendar |

### Admin / Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Render health check |
| `GET` | `/cache/stats` | Cache hit/miss statistics |
| `DELETE` | `/cache` | Clear all cached search results |
| `GET` | `/docs` | Interactive OpenAPI docs (Swagger UI) |

---

## Local Setup

```bash
# Clone
git clone https://github.com/HyungjoonYang/travel-planner-ai.git
cd travel-planner-ai

# Environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set GEMINI_API_KEY (required for AI/search features)

# Run
cd src && uvicorn app.main:app --reload --port 8000

# Open browser
open http://localhost:8000          # Frontend SPA
open http://localhost:8000/docs     # Swagger UI

# Test
pytest tests/ -v                   # 572 tests
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes (for AI features) | Google AI Studio API key |
| `DATABASE_URL` | No | SQLite path (default: `./travel_planner.db`) |

---

## Observability

```
observability/
├── logs/YYYY-MM-DD/run-HH-MM.json   # Per-run LTES trace
├── dashboard.json                    # Daily trends
├── error-budget.json                 # SLO budget tracking
└── postmortems/                      # Incident reviews
```

### LTES Metrics

| Signal | What it measures |
|--------|-----------------|
| **Latency** | Total run duration, pytest duration |
| **Traffic** | Commits/day, lines added/removed, files changed |
| **Errors** | Test failures, fix attempts, build errors |
| **Saturation** | Token usage estimate, backlog size |

### Error Budget

- SLO: 95% test pass rate, 90% run success rate
- `HEALTHY` (≥5% remaining) → new features allowed
- `WARNING` (1–5% remaining) → low-risk tasks only
- `EXHAUSTED` (<1% remaining) → feature freeze

---

## Project Files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Agent's brain — mission, constraints, workflow, tech decisions |
| `backlog.md` | Self-managed task board (Ready / In Progress / Done / Blocked) |
| `status.md` | Current health, LTES snapshot, recent run history |
| `render.yaml` | Render deployment configuration |
| `.env.example` | Environment variable template |
| `.claude/commands/evolve.md` | Main evolve loop command |
| `.claude/commands/monitor.md` | Health check command |
| `.claude/commands/fix.md` | Incident response command |

---

## Tests

572 tests across 18 test files:

| Test File | Coverage |
|-----------|----------|
| `test_travel_plans.py` | CRUD endpoints |
| `test_schemas.py` | Pydantic schema validation |
| `test_models.py` | ORM models |
| `test_ai.py` / `test_ai_plans.py` | Gemini service + AI endpoints |
| `test_structured_output.py` | Structured itinerary generation |
| `test_web_search.py` | Place search service + endpoint |
| `test_hotel_search.py` | Hotel search service + endpoint |
| `test_flight_search.py` | Flight search service + endpoint |
| `test_expenses.py` | Expense CRUD + budget summary |
| `test_calendar.py` | Google Calendar export |
| `test_cache.py` | TTLCache unit + integration |
| `test_error_handling.py` | Error handlers + request ID middleware |
| `test_integration.py` | Full plan lifecycle, multi-plan isolation |
| `test_frontend.py` | Static file serving |
| `test_deployment.py` | Dockerfile, render.yaml |
| `test_seed.py` | Seed data |
| `test_health.py` | Health endpoint |

---

## License

MIT
