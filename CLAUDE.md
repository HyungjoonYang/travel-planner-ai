# CLAUDE.md — Self-Evolving AI Travel Planner

## Mission

너는 AI 여행 플래너 앱을 **스스로 만들어가는 자율 에이전트**다.
사람은 이 파일과 초기 설정만 작성했다. 이후 코드 작성, 테스트, 버그 수정, 배포, 프로젝트 관리를 **모두 자율적으로 수행**한다.

> "Hope is not a strategy." — 모든 변경에는 테스트가 동반되어야 한다.

---

## 에이전트가 반드시 읽어야 할 파일

| 파일 | 내용 | 변경 주기 |
|------|------|-----------|
| `status.md` | 현재 Phase, health, 최근 변경, LTES 스냅샷 | 매 evolve run |
| `backlog.md` | 태스크 보드 (Ready / In Progress / Done) | 매 evolve run |
| `tech-decisions.md` | 기술 결정 로그 (모든 결정의 이유) | 새 결정 시 |
| `markdowns/*.md` | 기능 스펙 문서 (Architect가 참조) | 새 기능 기획 시 |
| `observability/error-budget.json` | Error Budget 상태 | 매 evolve run |

> **CLAUDE.md는 불변 원칙만 담는다.** 자주 바뀌는 상태는 위 파일들에서 확인한다.

---

## Product Requirements

### 한 줄 요약
여행 조건을 입력하면 AI가 일정을 생성하고, 저장/수정/공유할 수 있는 웹 앱.

### User Stories

1. **여행 계획 생성**: 사용자가 목적지, 날짜, 예산, 관심사(음식, 문화, 자연 등)를 입력하면 AI가 day-by-day 일정을 생성한다
2. **계획 관리**: 생성된 여행 계획을 저장, 조회, 수정, 삭제할 수 있다 (CRUD)
3. **장소 추천**: AI가 웹 검색을 통해 실제 장소(관광지, 맛집, 카페 등)를 추천하고 일정에 포함한다
4. **숙소/항공 검색**: 웹 검색으로 숙소/항공 옵션을 찾아서 추천한다
5. **비용 관리**: 여행 예산 대비 예상 비용을 추적한다 (항목별 지출 기록)
6. **캘린더 연동**: 확정된 일정을 Google Calendar에 동기화한다
7. **프론트엔드**: AI 채팅 + 실시간 에이전트 대시보드 (스펙: `markdowns/feat-chat-dashboard.md`)

### 핵심 데이터 (방향만 — 세부 설계는 에이전트가 결정)

- **TravelPlan**: 목적지, 시작일, 종료일, 예산, 관심사, 상태(draft/confirmed)
- **DayItinerary**: 날짜별 일정 (장소 목록, 이동 수단, 메모)
- **Place**: 장소명, 카테고리, 주소, 예상 비용, AI 추천 이유
- **Expense**: 항목명, 금액, 카테고리, 여행 계획 연결

### AI 활용 (Gemini API)

- **일정 생성**: 사용자 조건 기반으로 structured output (JSON) 생성
- **장소 추천**: 프롬프트에 목적지/관심사 포함 → 구체적 장소명과 이유 반환
- **비용 추정**: 장소별 예상 비용 포함
- 프롬프트 엔지니어링: Few-shot, CoT 등 적극 활용

### 비기능 요구사항

- API는 RESTful, JSON 응답
- 에러 시 적절한 HTTP 상태 코드와 메시지
- 모든 엔드포인트에 테스트
- `/health` 엔드포인트 (Render 헬스체크용)

### 에이전트에게: 세부 설계는 자유

위는 **방향**이다. 데이터 모델의 정확한 필드, API URL 설계, 프론트엔드 프레임워크, UI 레이아웃 등 세부 결정은 에이전트가 자율적으로 내린다. 결정할 때마다 `tech-decisions.md`에 이유와 함께 기록한다.

---

## Architecture Direction

- **Backend**: FastAPI + SQLite (경량, 빠른 개발)
- **Frontend**: vanilla JS SPA → Chat + Multi-Agent Dashboard로 전환 중
- **AI/LLM**: Google Gemini API (gemini-3.0-flash) — `google-genai` SDK 사용
- **Deployment**: Render (render.yaml 기반 자동 배포, push 시 auto-deploy)
- **Observability**: LTES (Latency, Traffic, Errors, Saturation) 기반 구조화 로그
- **Evolve**: Multi-agent pipeline (Coordinator → Architect → Builder → QA → Reporter)

---

## Workflow (Evolve Loop)

매 실행(cron trigger) 시 5개 에이전트가 순서대로 실행된다.
상세 지침은 `.claude/commands/evolve.md`와 `.claude/agents/*.md`를 참조한다.

```
🧠 Coordinator → 📐 Architect (조건부) → 🔨 Builder → 🧪 QA → 📝 Reporter
```

| Agent | 역할 | 산출물 |
|-------|------|--------|
| 🧠 Coordinator | 상태 파악, 태스크 배정 | `.evolve/handoff.json` |
| 📐 Architect | 스펙→태스크 기획 (Ready ≤ 2일 때만) | `backlog.md` 업데이트 |
| 🔨 Builder | 코드 구현 + 테스트 | 코드 + `.evolve/build-result.json` |
| 🧪 QA | 전체 검증 (tests, lint, 기준 충족) | `.evolve/qa-result.json` |
| 📝 Reporter | 기록, 상태 업데이트, PR 생성 | `status.md` + `tech-decisions.md` + PR |

에이전트 간 통신은 `.evolve/*.json` 파일로 핸드오프한다.

---

## Incident Response Playbook

테스트 실패 또는 에러 감지 시 아래 8단계를 따른다:

1. **Acknowledge**: 실패 내역을 로그에 기록
2. **Check Signals**: LTES 메트릭 확인 (최근 로그에서 에러 추세)
3. **Identify Changes**: `git log --oneline -10`으로 최근 변경사항 확인
4. **Localize**: 실패하는 테스트 → 관련 코드로 범위 좁히기
5. **Fix**: 수정 시도 (최대 3회)
6. **Verify**: 전체 테스트 재실행으로 확인
7. **Report**: 결과를 `status.md`에 기록
8. **Document**: `observability/postmortems/`에 postmortem 작성

### Escalation
- 3회 연속 fix 실패 → 해당 태스크 Blocked 처리
- `status.md` health를 RED로 변경
- Error Budget 차감

### Postmortem 형식
- blame-free: "어떤 코드가 문제"가 아니라 "어떤 시스템적 원인"
- 반드시 포함: Timeline, Root Cause, Action Items, MTTR 계산
- Action Items는 backlog.md에 새 태스크로 추가

---

## Constraints (수정 불가)

이 섹션의 규칙은 에이전트가 **절대 수정하지 않는다**.

1. 한 번의 실행에서 **1개의 task만** 수행
2. **테스트 없는 코드는 커밋하지 않음**
3. 기존 테스트가 깨지면 **fix 우선** (새 기능 개발 중단)
4. 로그는 반드시 **LTES 구조화 형식**으로 작성
5. Error Budget EXHAUSTED 시 **기능 개발 동결**
6. `CLAUDE.md`의 이 "Constraints" 섹션은 **수정 금지**
7. `.env` 파일이나 시크릿을 코드에 **하드코딩 금지**
8. 새 import/dependency 추가 시 **requirements.txt 즉시 업데이트**

---

## Constraints (에이전트 추가 가능)

에이전트가 postmortem이나 경험에서 배운 규칙을 여기에 추가한다.

_(에이전트가 학습하면서 추가)_

---

## Project Structure

```
travel-planner-ai/
├── CLAUDE.md                    # 불변 원칙 (이 파일)
├── status.md                    # 가변 상태 (Phase, health, LTES)
├── backlog.md                   # 태스크 보드
├── tech-decisions.md            # 기술 결정 로그
├── .claude/
│   ├── commands/                # 에이전트 커맨드
│   │   ├── evolve.md            # Multi-agent 오케스트레이터
│   │   ├── monitor.md           # 헬스체크 + LTES
│   │   └── fix.md               # Incident Response
│   └── agents/                  # 에이전트별 역할 정의
│       ├── coordinator.md       # 🧠 상태 파악 + 태스크 배정
│       ├── architect.md         # 📐 스펙→태스크 기획
│       ├── builder.md           # 🔨 코드 구현
│       ├── qa.md                # 🧪 품질 검증
│       └── reporter.md          # 📝 기록 + PR 생성
├── .github/workflows/
│   ├── evolve.yml               # Multi-agent evolve (5-step pipeline)
│   ├── ci.yml                   # PR 테스트 + auto-merge
│   ├── qa.yml                   # Playwright E2E (daily cron)
│   └── monitor.yml              # 헬스체크 (가벼운 실행)
├── .evolve/                     # 에이전트 간 핸드오프 (ephemeral, .gitignore)
├── markdowns/                   # 기능 스펙 문서 (Architect가 참조)
├── e2e/                         # Playwright E2E 테스트
├── observability/
│   ├── logs/                    # 실행별 LTES 로그
│   ├── traces/                  # Trace + Span 로그
│   ├── postmortems/             # 장애 사후 분석
│   ├── dashboard.json           # LTES 대시보드 데이터
│   └── error-budget.json        # Error Budget 추적
├── src/                         # 앱 소스 코드
├── tests/                       # 단위/통합 테스트
├── render.yaml                  # Render 배포 설정
├── requirements.txt             # Python dependencies
├── .env.example                 # 환경변수 템플릿
└── README.md                    # 프로젝트 설명
```

---

## Build & Run Commands

```bash
# 환경 설정
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 실행
cd src && uvicorn app.main:app --reload --port 8000

# 테스트
pytest tests/ -v

# 린트
ruff check src/ tests/
```
