# Travel Planner AI

> A self-evolving AI travel planner — built entirely by autonomous AI agents.

## What is this?

This repository is an experiment in **AI-native software development**. A human wrote only the initial configuration (`CLAUDE.md`, workflows, backlog). Everything else — code, tests, bug fixes, deployment — is done autonomously by an AI agent running on a cron schedule.

**Zero human code contributions.** Check the git log.

## How it works

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
│  1. Health Check (run tests)                          │
│  2. Read status.md + backlog.md                       │
│  3. Pick next task                                    │
│  4. Implement + write tests                           │
│  5. Record LTES metrics                               │
│  6. Commit & push                                     │
│  7. Slack notification                                │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                  Render Auto-Deploy                    │
│              Push to main → deploy                    │
└─────────────────────────────────────────────────────┘
```

## Observability

The agent monitors itself using **LTES (Latency, Traffic, Errors, Saturation)** — the Four Golden Signals from Google SRE:

- **Latency**: Time per evolve run, runs to complete a task
- **Traffic**: Commits/day, lines changed
- **Errors**: Test failure rate, fix attempts
- **Saturation**: Token usage, backlog size

See `observability/` for structured logs, traces, postmortems, and dashboards.

## Key Files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Agent's brain — mission, rules, architecture |
| `backlog.md` | Self-managed task board |
| `status.md` | Current system status |
| `observability/` | LTES logs, traces, postmortems, dashboards |
| `.claude/commands/` | Agent commands (evolve, monitor, fix) |

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
# Edit .env with your API keys

# Run
cd src && uvicorn app.main:app --reload --port 8000

# Test
pytest tests/ -v
```

## Architecture

- **Backend**: FastAPI + SQLite
- **AI**: Google Gemini API
- **Deployment**: Render (free tier, auto-deploy)
- **CI/CD**: GitHub Actions (cron-based autonomous agent)
- **Observability**: LTES-based structured logging

## License

MIT
