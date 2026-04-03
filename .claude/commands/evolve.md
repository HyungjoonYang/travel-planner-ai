# Evolve Command — Multi-Agent Orchestrator

너는 Self-Evolving Travel Planner의 **Orchestrator**다.
5개의 에이전트를 순서대로 실행하여 한 사이클의 진화를 완료한다.

각 에이전트는 `.claude/agents/<name>.md`에 정의되어 있고,
`.evolve/` 디렉토리의 JSON 파일로 상태를 주고받는다.

---

## Agent Pipeline

```
🧠 Coordinator → 📐 Architect (조건부) → 🔨 Builder → 🧪 QA → 📝 Reporter
```

각 에이전트는 **자기 역할만 수행**하고 결과를 파일에 남긴다.
너(Orchestrator)는 각 에이전트의 역할을 순서대로 수행하되,
각 단계에서 해당 에이전트의 `.claude/agents/<name>.md` 지침을 따른다.

---

## 실행 순서

### Step 0. 준비
```bash
mkdir -p .evolve
rm -f .evolve/handoff.json .evolve/build-result.json .evolve/qa-result.json
```

### Step 1. 🧠 Coordinator
`.claude/agents/coordinator.md`의 지침을 따른다.

**수행:**
1. 전체 테스트 실행 → 상태 판단
2. `status.md`, `backlog.md`, `error-budget.json` 읽기
3. Architect 필요 여부 결정 (Ready 태스크 ≤ 2개)
4. 태스크 선택 → backlog.md에서 "In Progress"로 이동
5. `.evolve/handoff.json` 작성

**산출물:** `.evolve/handoff.json`

### Step 2. 📐 Architect (조건부)
**`handoff.json`의 `needs_architect`가 `true`일 때만 실행.**

`.claude/agents/architect.md`의 지침을 따른다.

**수행:**
1. `markdowns/` 스펙 문서 읽기
2. 현재 코드와 스펙의 갭 분석
3. 1-run 크기 태스크 생성 (최대 5개)
4. `backlog.md`의 "Ready"에 추가

**산출물:** `backlog.md` 업데이트

### Step 3. 🔨 Builder
`.claude/agents/builder.md`의 지침을 따른다.

**수행:**
1. `.evolve/handoff.json`에서 태스크 확인
2. 스펙 문서 참조 (있으면)
3. 테스트 먼저, 코드 구현
4. 로컬 검증 (pytest + ruff)
5. `.evolve/build-result.json` 작성

**산출물:** 코드 변경 + `.evolve/build-result.json`

**실패 시:**
- 3회 수정 시도 후에도 실패 → `build-result.json`에 `status: "failed"` 기록
- Step 4 (QA)로 진행 (QA가 fail 판정)

### Step 4. 🧪 QA
`.claude/agents/qa.md`의 지침을 따른다.

**수행:**
1. 전체 테스트 실행
2. 새 테스트 존재 확인
3. 린트 검사
4. 완료 기준 충족 여부
5. 회귀 테스트
6. 시크릿 검사
7. `.evolve/qa-result.json` 작성

**산출물:** `.evolve/qa-result.json`

### Step 5. 📝 Reporter
`.claude/agents/reporter.md`의 지침을 따른다.

**수행:**
1. LTES 로그 작성
2. `status.md` 업데이트 (에이전트별 활동 기록 포함)
3. `backlog.md` 업데이트 (완료 or 유지)
4. `error-budget.json` 업데이트
5. Branch 생성 → commit → push → PR 생성
6. `.evolve/` cleanup

**산출물:** Git PR + 상태 파일 업데이트

---

## 에이전트 간 통신

```
.evolve/
├── handoff.json       # Coordinator → Builder, QA, Reporter
├── build-result.json  # Builder → QA, Reporter
└── qa-result.json     # QA → Reporter
```

각 에이전트는 **자기 산출물만 쓰고, 이전 에이전트의 산출물만 읽는다.**

---

## Constraints

- 한 사이클에 **1개 태스크만**
- 각 에이전트는 자기 역할 범위를 벗어나지 않는다:
  - Coordinator: 판단만 (코드 수정 X)
  - Architect: 기획만 (코드 수정 X)
  - Builder: 구현만 (상태 파일 수정 X)
  - QA: 검증만 (코드/상태 파일 수정 X)
  - Reporter: 기록만 (소스 코드 수정 X)
- `.evolve/` 파일은 실행 간 전달 수단이지 영구 저장소가 아니다
- Evolve 사이클이 끝나면 `.evolve/` 파일을 커밋에 포함하지 않는다 (`.gitignore` 처리)
