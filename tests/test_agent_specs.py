"""Tests for agent instruction file specs — validates required content in .claude/agents/*.md."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
REPORTER_MD = ROOT / ".claude" / "agents" / "reporter.md"


class TestReporterIncidentAutoIssue:
    """Task #55: reporter.md must include incident auto-issue instructions."""

    def _content(self) -> str:
        return REPORTER_MD.read_text()

    def test_reporter_md_exists(self):
        assert REPORTER_MD.exists(), "reporter.md must exist"

    def test_reporter_checks_consecutive_failures(self):
        content = self._content()
        assert "consecutive" in content.lower(), (
            "reporter.md must mention consecutive failure tracking"
        )

    def test_reporter_creates_bug_issue_on_threshold(self):
        content = self._content()
        assert "bug" in content and "blocked" in content, (
            "reporter.md must reference 'bug' and 'blocked' labels for auto-issue"
        )

    def test_reporter_uses_three_failure_threshold(self):
        content = self._content()
        assert "3" in content or "three" in content.lower() or "≥3" in content, (
            "reporter.md must specify ≥3 failure threshold"
        )

    def test_reporter_skips_if_open_bug_exists(self):
        content = self._content()
        # Must instruct to skip creation when an open bug issue already exists
        assert "open" in content.lower() and (
            "skip" in content.lower() or "already" in content.lower() or "exist" in content.lower()
        ), "reporter.md must skip issue creation if an open bug already exists"

    def test_reporter_includes_failure_details_in_issue(self):
        content = self._content()
        # Issue body must include failure details from qa-result.json
        assert "qa-result" in content or "failure detail" in content.lower() or "issues" in content.lower(), (
            "reporter.md must include failure details in the auto-created bug issue"
        )

    def test_reporter_resets_failure_count_on_success(self):
        content = self._content()
        assert "reset" in content.lower() or "0" in content, (
            "reporter.md must reset consecutive failure count when QA passes"
        )

    def test_reporter_tracks_failures_in_error_budget(self):
        content = self._content()
        assert "consecutive_qa_failures" in content or "error-budget" in content, (
            "reporter.md must track consecutive failures in error-budget.json or similar"
        )

    def test_reporter_uses_gh_issue_create(self):
        content = self._content()
        assert "gh issue create" in content, (
            "reporter.md must include the gh issue create command"
        )

    def test_reporter_uses_gh_issue_list_to_check_open(self):
        content = self._content()
        assert "gh issue list" in content, (
            "reporter.md must use gh issue list to check for existing open bug issues"
        )


class TestReporterWeeklyDiscussion:
    """Task #61: reporter.md must include weekly Discussion summary instructions."""

    def _content(self) -> str:
        return REPORTER_MD.read_text()

    def test_reporter_posts_discussion_on_monday_or_phase_change(self):
        content = self._content()
        assert ("monday" in content.lower() or "월요일" in content) and (
            "phase" in content.lower() or "phase change" in content.lower()
        ), "reporter.md must trigger Discussion post on Monday or Phase change"

    def test_reporter_discussion_title_format(self):
        content = self._content()
        assert "[Weekly]" in content, (
            "reporter.md must specify Discussion title format containing '[Weekly]'"
        )

    def test_reporter_discussion_title_includes_phase(self):
        content = self._content()
        assert "진행 현황" in content, (
            "reporter.md Discussion title must include '진행 현황'"
        )

    def test_reporter_discussion_body_includes_tasks_done(self):
        content = self._content()
        assert "task" in content.lower() or "태스크" in content, (
            "reporter.md Discussion body must mention completed tasks"
        )

    def test_reporter_discussion_body_includes_test_count(self):
        content = self._content()
        # Check that the Weekly section mentions test count
        weekly_idx = content.find("[Weekly]")
        section = content[weekly_idx:weekly_idx + 2000] if weekly_idx != -1 else ""
        assert "test" in section.lower() or "테스트" in section, (
            "reporter.md Discussion body must include test count"
        )

    def test_reporter_discussion_body_includes_pr_links(self):
        content = self._content()
        weekly_idx = content.find("[Weekly]")
        section = content[weekly_idx:weekly_idx + 2000] if weekly_idx != -1 else ""
        assert "pr" in section.lower() or "pull request" in section.lower(), (
            "reporter.md Discussion body must include PR links"
        )

    def test_reporter_discussion_uses_gh_api(self):
        content = self._content()
        assert "gh api" in content or "discussions" in content.lower(), (
            "reporter.md must use gh api for Discussion creation"
        )

    def test_reporter_discussion_skips_on_api_error(self):
        content = self._content()
        assert (
            "silent" in content.lower()
            or "skip" in content.lower()
            or "2>/dev/null" in content
            or "|| true" in content
            or "ignore" in content.lower()
        ), "reporter.md must silently skip Discussion post on API error"

    def test_reporter_discussion_category_retrospectives(self):
        content = self._content()
        assert "retrospective" in content.lower() or "Retrospectives" in content, (
            "reporter.md Discussion must use 'Retrospectives' category"
        )
