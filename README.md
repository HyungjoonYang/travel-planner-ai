# Travel Planner AI

> A human wrote one file. AI agents built everything else.

`CLAUDE.md` — a single markdown file — defines the mission, constraints, and architecture direction. From that, autonomous AI agents have written every line of code, every test, every deployment config, every bug fix. No human code contributions. 203 commits and counting.

## The Experiment

**Question**: What happens if you give an AI agent a product spec, a set of engineering constraints, and a cron schedule — then step back?

**Answer**: It builds a production web app from scratch, evolves it through 10 phases, writes 1,642 tests, resolves its own incidents, and makes its own technical decisions.

This repo is the result. The travel planner app is real and works — but the interesting part is *how it got built*.

---

## How the AI Builds Itself

A **5-agent pipeline** runs autonomously on a cron schedule (GitHub Actions, every 30 min overnight):

```
Coordinator  -->  Architect  -->  Builder  -->  QA  -->  Reporter
(what to do)   (how to do it)  (write code)  (verify)  (ship it)
```

Each run, the system:

1. **Coordinator** reads GitHub Issues, checks health, picks the highest-priority task
2. **Architect** designs the implementation (only activates when backlog runs low)
3. **Builder** writes code + tests in a feature branch
4. **QA** runs the full test suite (1,642 tests), lint, integration checks
5. **Reporter** creates a PR, CI runs, auto-merges on green, updates docs

Agents communicate via file-based handoff (`.evolve/*.json`). Task state lives in GitHub Issues. Every technical decision is logged with reasoning in `tech-decisions.md`.

### Self-Healing

When tests fail, the system follows an 8-step incident response playbook:

- Retry up to 3 times with different approaches
- If stuck: mark task as `blocked`, set health to RED, write a postmortem
- Error Budget tracks success rate — when exhausted, **feature development freezes** until stability is restored

### Constraints the Agent Cannot Break

These rules are hardcoded in `CLAUDE.md` and the agent is not allowed to modify them:

- 1 task per run (no multi-tasking)
- No code without tests
- Broken tests = fix first, new features wait
- No hardcoded secrets
- Error budget exhausted = feature freeze

The agent *can* add new constraints — learned from its own postmortems. So far it has added 6 rules, including "integration tests must hit real flows, not mocks" and "silent exception handling is forbidden."

---

## Evolution Timeline

| Phase | What Happened | Tasks |
|-------|--------------|-------|
| 1-3 | Basic CRUD API — travel plans, expenses, health endpoint | ~15 |
| 4-5 | AI integration — Gemini itinerary generation, web search grounding | ~15 |
| 6-7 | Search features — hotels, flights, caching, calendar export | ~20 |
| 8-9 | Chat engine — intent extraction, SSE streaming, expense/weather/plan commands | ~35 |
| 10 | Multi-agent dashboard — 7 real-time agents, UI redesign, Playwright E2E | ~24 |

**109 tasks completed. 164 autonomous runs. 10 phases. 1 human-written file.**

---

## What It Built

A chat-driven travel planner where you describe your trip in natural language, and a team of AI agents researches and builds your itinerary in real time.

- **Chat-first**: no forms — AI extracts destination, dates, budget, interests from conversation
- **7 specialized agents** (Coordinator, Planner, Place Scout, Hotel Finder, Flight Finder, Budget Analyst, Secretary) work simultaneously with live status in the dashboard
- **20+ chat intents**: create plans, add/remove/swap/move places, set day labels, track expenses, get weather, share plans — all via natural language
- **Live on Render**: auto-deploys on every merge to main

### Tech Stack

FastAPI + SQLite + Gemini 3.0 Flash + Vanilla JS SPA. No build step, no Node.js, no framework overhead. The agent chose this stack itself (reasoning in `tech-decisions.md`).

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Human-written code | 0 lines |
| Total commits | 203 |
| Autonomous runs | 164 |
| Tasks completed | 109 |
| Tests | 1,642 (pytest) + Playwright E2E |
| Phases evolved | 10 |
| Agent-added constraints | 6 |
| Postmortems written | by the agent, for the agent |

---

## Try It Locally

```bash
git clone https://github.com/HyungjoonYang/travel-planner-ai.git
cd travel-planner-ai

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env  # Set GEMINI_API_KEY

cd src && uvicorn app.main:app --reload --port 8000
```

---

## Key Files

| File | What It Does |
|------|-------------|
| `CLAUDE.md` | The only human-written file. Mission, constraints, architecture direction. |
| `status.md` | Current phase, health, LTES metrics — updated every run |
| `tech-decisions.md` | Every technical decision with reasoning — written by the agent |
| `observability/error-budget.json` | SLO tracking — controls whether new features are allowed |
| `.claude/agents/` | Role definitions for the 5 evolve agents |

---

## License

MIT
