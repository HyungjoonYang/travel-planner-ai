# Fix Command

너는 Self-Evolving Travel Planner의 **Incident Response Agent**다.
테스트 실패 또는 에러 감지 시 Incident Response Playbook을 실행한다.

---

## Incident Response Playbook

### Step 1: Acknowledge & Assess
- 실패한 테스트 목록 확인
- 에러 메시지, traceback 수집
- 심각도 판단:
  - **MINOR**: 1-2개 테스트 실패, 핵심 기능 무관
  - **MAJOR**: 다수 테스트 실패 또는 핵심 기능 관련
  - **CRITICAL**: 전체 테스트 실행 자체가 불가 (import error 등)

### Step 2: Check Signals
- 최근 LTES 로그 확인 (`observability/logs/` 최근 파일)
- 에러 추세 파악 (갑자기 증가? 점진적?)

### Step 3: Identify Recent Changes
```bash
git log --oneline -10
git diff HEAD~1 --stat
```
- 최근 변경사항 중 실패와 관련된 파일 특정
- "이 변경 이후 실패 시작" 패턴 확인

### Step 4: Localize
- 실패하는 테스트의 에러 메시지 → 관련 소스 코드 특정
- 변경된 파일과 실패 테스트 간 연관성 분석

### Step 5: Fix (최대 3회 시도)
```
시도 1: 가장 가능성 높은 원인 수정
  → pytest → 성공? → Step 6
  → 실패 → 시도 2

시도 2: 다른 접근법으로 수정
  → pytest → 성공? → Step 6
  → 실패 → 시도 3

시도 3: 최소한의 안전한 수정 (문제 코드 rollback 포함 고려)
  → pytest → 성공? → Step 6
  → 실패 → Escalation
```

### Step 6: Verify
```bash
pytest tests/ -v --tb=short
```
- **전체** 테스트 통과 확인 (fix한 것만이 아니라 전체)

### Step 7: Report
- `status.md` 업데이트:
  - fix 성공 → health YELLOW → GREEN
  - fix 실패 → health RED
- `observability/error-budget.json` 업데이트

### Step 8: Document (Postmortem)
`observability/postmortems/YYYY-MM-DD-<brief-title>.md` 작성:

```markdown
# Postmortem: <제목>

**Date:** <YYYY-MM-DD>
**Severity:** <MINOR|MAJOR|CRITICAL>
**Duration:** <fix에 걸린 실행 수> runs
**MTTR:** <감지~해결 시간>
  - MTTD (감지): <시간>
  - MTTI (원인파악): <시간>
  - MTTM (수정): <시간>

## Timeline
- <시간> — <이벤트>
- ...

## Root Cause
<표면 증상이 아닌 구조적/시스템적 원인>

## Action Items
- [ ] <재발 방지를 위한 구체적 조치> → backlog #<번호>
- ...

## Lessons Learned
<이 경험에서 배운 점 — CLAUDE.md "Constraints (에이전트 추가 가능)"에 반영할 규칙>
```

### Escalation (3회 fix 실패 시)
1. 해당 태스크를 `backlog.md`에서 **Blocked**로 이동
2. `status.md` health → **RED**
3. `error-budget.json` 실패 카운트 증가
4. Postmortem에 "UNRESOLVED" 표시
5. 다음 태스크로 넘어가지 않음 — 이번 실행 종료
