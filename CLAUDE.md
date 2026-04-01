# CLAUDE.md — Self-Evolving AI Travel Planner

## Mission

너는 AI 여행 플래너 앱을 **스스로 만들어가는 자율 에이전트**다.
사람은 이 파일과 초기 설정만 작성했다. 이후 코드 작성, 테스트, 버그 수정, 배포, 프로젝트 관리를 **모두 자율적으로 수행**한다.

> "Hope is not a strategy." — 모든 변경에는 테스트가 동반되어야 한다.

---

## Architecture Direction

- **Backend**: FastAPI + SQLite (경량, 빠른 개발)
- **Frontend**: 에이전트가 결정 (React, vanilla JS, or HTMX — 결정 시 아래 Tech Stack Decisions Log에 기록)
- **AI/LLM**: Google Gemini API (여행 계획 생성, 장소 추천, 일정 최적화) — `google-genai` SDK 사용
- **Deployment**: Render (render.yaml 기반 자동 배포, push 시 auto-deploy)
- **Observability**: LTES (Latency, Traffic, Errors, Saturation) 기반 구조화 로그

---

## Workflow (Evolve Loop)

매 실행(cron trigger) 시 아래 순서를 **반드시** 따른다:

### Step 1: Health Check
```
기존 테스트 전체 실행
├── 실패 있음 → Incident Response 모드 (.claude/commands/fix.md)
└── 전부 통과 → Step 2로
```

### Step 2: Status Check
- `status.md` 읽고 현재 상태 파악
- `observability/error-budget.json` 확인
  - EXHAUSTED → 안정화/리팩토링 태스크만 선택 (새 기능 금지)
  - WARNING → 리스크 낮은 태스크만
  - HEALTHY → 자유롭게 선택

### Step 3: Task Selection
- `backlog.md`에서 다음 태스크 선택
  - "In Progress"에 이미 있으면 이어서 진행
  - 없으면 "Ready"에서 우선순위 최상위 선택
  - 태스크를 "In Progress"로 이동

### Step 4: Implementation
- 코드 작성
- **반드시** 테스트 작성 (테스트 없는 코드는 커밋 금지)
- 전체 테스트 실행 → 통과 확인

### Step 5: Record & Report
- LTES 실행 로그 기록 (`observability/logs/`)
- `status.md` 업데이트
- `backlog.md` 업데이트 (완료 태스크 이동, 필요시 새 태스크 추가)
- `observability/error-budget.json` 업데이트
- `observability/dashboard.json` 업데이트
- 변경사항 commit & push

### Step 6: Daily Summary (마지막 실행 시)
- UTC 21:00 (KST 06:00) 실행이면 그날의 성과 요약 생성
- `status.md`에 일일 요약 추가

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

## Tech Stack Decisions Log

에이전트가 기술 결정을 내릴 때마다 이유와 함께 여기에 기록한다.
다음 실행 시 이전 결정을 참고하여 일관성을 유지한다.

| Date | Decision | Reason |
|------|----------|--------|
| _(에이전트가 기록)_ | | |

---

## Project Structure

```
travel-planner-ai/
├── CLAUDE.md                    # 이 파일 (에이전트의 두뇌)
├── .claude/commands/            # 에이전트 커맨드
│   ├── evolve.md                # 메인 진화 루프
│   ├── monitor.md               # 헬스체크 + LTES
│   └── fix.md                   # Incident Response
├── .github/workflows/
│   ├── evolve.yml               # cron 기반 에이전트 실행 (야간)
│   └── monitor.yml              # 헬스체크 (가벼운 실행)
├── status.md                    # 현재 상태 (에이전트 관리)
├── backlog.md                   # 태스크 보드 (에이전트 관리)
├── observability/
│   ├── logs/                    # 실행별 LTES 로그
│   ├── traces/                  # Trace + Span 로그
│   ├── postmortems/             # 장애 사후 분석
│   ├── dashboard.json           # LTES 대시보드 데이터
│   └── error-budget.json        # Error Budget 추적
├── src/                         # 앱 소스 코드 (에이전트가 작성)
├── tests/                       # 테스트 (에이전트가 작성)
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

---

## Current Phase

Phase 1: POC — FastAPI 프로젝트 초기화 및 기본 CRUD

_(에이전트가 phase 전환 시 업데이트)_
