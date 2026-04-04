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
