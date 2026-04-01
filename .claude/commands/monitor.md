# Monitor Command

너는 Self-Evolving Travel Planner의 **Monitor Agent**다.
시스템 건강 상태를 점검하고 LTES 메트릭을 수집한다.

---

## 실행 순서

### 1. 테스트 실행
```bash
pytest tests/ -v --tb=short 2>&1
```
- 테스트 파일이 없으면 → SKIP으로 기록
- 결과: 전체 수, 통과 수, 실패 수 기록

### 2. LTES 메트릭 수집

**Latency (지연)**
- 이번 실행 소요 시간 (start ~ end)
- 최근 5회 실행 평균 소요 시간

**Traffic (트래픽)**
- `git log --oneline --since="24 hours ago"` → 최근 24시간 커밋 수
- `git diff --stat HEAD~1` → 최근 변경량 (lines added/removed)

**Errors (에러)**
- 테스트 실패 수
- 최근 5회 실행 중 실패 횟수
- `observability/logs/` 최근 로그에서 에러 카운트

**Saturation (포화도)**
- `backlog.md` 잔여 태스크 수 (Ready + In Progress)
- `observability/logs/` 디렉토리 크기
- 최근 실행의 토큰 사용량 추세

### 3. Health Status 판단

| Status | 조건 |
|--------|------|
| GREEN | 모든 테스트 통과, Error Budget healthy |
| YELLOW | 테스트 실패 있지만 fix 시도 중, 또는 Error Budget warning |
| RED | 3회 연속 fix 실패, 또는 Error Budget exhausted |

### 4. 상태 업데이트
- `status.md`에 LTES 스냅샷 업데이트
- `observability/dashboard.json` 업데이트
- `observability/error-budget.json` 업데이트

### 5. Commit
상태 파일 변경사항만 커밋:
```bash
git add status.md observability/
git commit -m "monitor: health check — <GREEN|YELLOW|RED>

LTES: L=<latency>ms T=<commits>/day E=<error_rate>% S=<backlog_remaining> tasks"
git push origin main
```
