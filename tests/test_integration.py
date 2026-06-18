"""End-to-end planning test with a fake tracker and no LLM (offline)."""

from pilot import cli
from pilot.models import Issue


class FakeTracker:
    def __init__(self, url, secret):
        self.issues = {
            1: Issue(id=1, title="Fix typo", description="typo in README", status="ready", project="demo"),
            2: Issue(id=2, title="Add field", description="schema change", status="ready", project="demo"),
            3: Issue(id=3, title="Use field", description="depends on #2", status="ready", project="demo"),
        }

    def get_issue(self, issue_id):
        return self.issues[issue_id]

    def list_issues(self, project=None, status=None, limit=None):
        return [i for i in self.issues.values() if i.status == status]

    def list_projects(self):
        return ["demo"]


def test_dry_run_writes_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUESDB_MCP_SECRET", "test-secret")
    monkeypatch.setattr("pilot.issuesdb.Tracker", FakeTracker)

    rc = cli.run(["demo", "--no-llm", "--dry-run", "--plan-dir", str(tmp_path)])
    assert rc == 0

    plans = list(tmp_path.glob("DELIVERY_PLAN-*.md"))
    assert len(plans) == 1
    text = plans[0].read_text()
    assert "# Delivery Plan" in text
    # explicit #2 -> #3 dependency must order batch with #2 before the one with #3
    assert text.index("#2") < text.index("#3")
    # nothing executed in dry run → all batches still pending
    assert "Execution Summary" not in text


def test_ids_mode_with_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUESDB_MCP_SECRET", "test-secret")
    monkeypatch.setattr("pilot.issuesdb.Tracker", FakeTracker)

    # Stub the dispatch so no real subprocess runs.
    import pilot.execute as execute

    monkeypatch.setattr(
        execute, "_default_runner",
        lambda argv, timeout: "https://github.com/demo/repo/pull/1",
    )

    rc = cli.run(["1", "--no-llm", "--plan-dir", str(tmp_path)])
    assert rc == 0
    text = next(tmp_path.glob("DELIVERY_PLAN-*.md")).read_text()
    assert "✅ done" in text
    assert "## Execution Summary" in text
    assert "- Completed: 1" in text
