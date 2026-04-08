# Tech Stack Decisions Log

에이전트가 기술 결정을 내릴 때마다 이유와 함께 여기에 기록한다.
다음 실행 시 이전 결정을 참고하여 일관성을 유지한다.

> **Builder Agent**: 새 기술 결정을 내리면 반드시 이 파일에 기록한다.

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04-01 | SQLAlchemy mapped_column / Mapped[T] (2.0 style) | Type-safe ORM declarations; native Python type hints; compatible with Pydantic v2 `model_validate` |
| 2026-04-01 | Pydantic v2 schemas with `from_attributes=True` | FastAPI native integration; strict validation (pattern, gt, ge); partial Update model via Optional fields |
| 2026-04-01 | interests stored as comma-separated string (not JSON array) | Simpler SQLite storage; easy to read/write; can be split by AI prompt layer |
| 2026-04-01 | Web search via Gemini `google_search` grounding tool (not a separate search API) | No extra API key required; Gemini natively fetches and grounds answers in real-time Google Search results; keeps dependency count low |
| 2026-04-01 | Frontend: vanilla JS SPA served via FastAPI `StaticFiles` + `FileResponse` | No build step, no Node.js toolchain; single `index.html` with embedded CSS and JS; served at `GET /` and `/static/*`; consistent with lightweight backend-first architecture |
| 2026-04-03 | Gemini model: gemini-2.0-flash → gemini-3.0-flash | gemini-2.0-flash deprecated (404); 3.0-flash is current stable model |
| 2026-04-03 | Multi-agent evolve pipeline (5 agents with file-based handoff) | Single-agent evolve lacked separation of concerns; now each agent has focused role + clear input/output contract; enables parallel QA and better observability |
| 2026-04-03 | SSE (not WebSocket) for chat streaming | Unidirectional server→client streaming; no extra dependencies; FastAPI StreamingResponse native support; auto-reconnect built-in |
| 2026-04-03 | PR-based evolve (not direct push to main) | Safety: CI tests + auto-merge on pass; failed changes don't reach main; human review possible via `evolve-needs-review` label |
| 2026-04-08 | OpenChrome MCP for visual verification (Playwright MCP 보완) | DOM Mode로 페이지당 ~12K 토큰 (Playwright ~180K 대비 15x 압축); CDP 직접 통신; Ralph Engine 7단계 자동 에러 복구; CI에서는 Playwright fallback 유지 |
| 2026-04-08 | Evolve model pinning: Opus 4.6 | harness-engineering 원칙에 따라 모델 명시적 고정; 예기치 않은 모델 변경으로 인한 파이프라인 동작 변화 방지 |
| 2026-04-08 | Per-agent step timeout + Builder-QA inner retry loop | 5-Layer Defense 중 per-cron timeout 적용; QA 실패 시 같은 run 내 1회 재시도로 효율 2배 향상 |
| 2026-04-08 | Per-issue failure history tracking | 동일 이슈 3회 연속 실패 시 자동 blocked 처리; 무한 재시도 순환 방지 |
