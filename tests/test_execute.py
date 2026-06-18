from pilot.execute import (
    build_context_block,
    dispatch_command,
    parse_signals,
    run_batches,
)
from pilot.models import (
    STATUS_AWAITING,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    Batch,
    DepEdge,
    DeliveryPlan,
)


def test_parse_signals_success():
    out = "all done\nOpened https://github.com/acme/repo/pull/42 ready"
    r = parse_signals(out)
    assert r.status == STATUS_DONE
    assert r.pr_url == "https://github.com/acme/repo/pull/42"


def test_parse_signals_tier3_takes_precedence_over_pr_url():
    out = ("PR: https://github.com/acme/repo/pull/9\n"
           "Orchestrator: Tier 3 — requires human merge approval.")
    r = parse_signals(out)
    assert r.status == STATUS_AWAITING
    assert r.pr_url == "https://github.com/acme/repo/pull/9"


def test_parse_signals_blocked():
    r = parse_signals("Orchestrator: development blocked — see output.")
    assert r.status == STATUS_BLOCKED


def test_parse_signals_failed_when_no_signal():
    assert parse_signals("nothing useful here").status == STATUS_FAILED


def test_dispatch_command_is_always_orchestrate():
    argv = dispatch_command([1, 2], "ctx", dispatch="opencode")
    assert argv[:3] == ["opencode", "run", "--prompt"]
    assert "/orchestrate 1 2" in argv[-1]
    assert "work-issuesdb" not in argv[-1]

    argv = dispatch_command([3], "", dispatch="claude")
    assert argv[0] == "claude" and argv[1] == "-p"
    assert "/orchestrate 3" in argv[-1]


def test_build_context_block_forwards_issue_bodies():
    block = build_context_block("/root", "be careful", "deps", issue_bodies="### #1 x")
    assert "Project root: /root" in block
    assert "already fetched" in block
    assert "### #1 x" in block


def test_run_batches_skips_dependents_of_blocked():
    plan = DeliveryPlan(batches=[
        Batch(index=1, theme="t1", tier=2, issue_ids=[1]),
        Batch(index=2, theme="t2", tier=2, issue_ids=[2]),
    ])
    edges = [DepEdge(before=1, after=2, reason="prereq")]

    def runner(argv, timeout):
        # batch 1 (issue 1) blocks; batch 2 should be skipped, never dispatched
        return "Orchestrator: development blocked"

    counts = run_batches(plan, edges, runner=runner)
    assert plan.batches[0].status == STATUS_BLOCKED
    assert plan.batches[1].status == STATUS_SKIPPED
    assert counts["skipped"] == 1


def test_run_batches_success_path_counts_and_updates():
    plan = DeliveryPlan(batches=[Batch(index=1, theme="t", tier=1, issue_ids=[1])])
    seen = []

    def runner(argv, timeout):
        return "https://github.com/a/b/pull/5"

    counts = run_batches(plan, [], runner=runner, on_update=seen.append)
    assert plan.batches[0].status == STATUS_DONE
    assert plan.batches[0].status_detail == "https://github.com/a/b/pull/5"
    assert counts["completed"] == 1
    assert seen == [plan.batches[0]]


def test_run_batches_dispatch_exception_marks_failed():
    plan = DeliveryPlan(batches=[Batch(index=1, theme="t", tier=2, issue_ids=[1])])

    def runner(argv, timeout):
        raise TimeoutError("boom")

    run_batches(plan, [], runner=runner)
    assert plan.batches[0].status == STATUS_FAILED
    assert "boom" in plan.batches[0].status_detail
