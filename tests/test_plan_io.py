from pilot import plan_io
from pilot.models import (
    STATUS_AWAITING,
    STATUS_BLOCKED,
    STATUS_DONE,
    Batch,
    DeliveryPlan,
)


def _plan():
    return DeliveryPlan(
        batches=[
            Batch(index=1, theme="proj — Tier 3 critical", tier=3, issue_ids=[2],
                  rationale="de-risk"),
            Batch(index=2, theme="proj — Tier 1 cleanup", tier=1, issue_ids=[3, 4],
                  rationale="bundle"),
        ],
        needs_grooming=[(9, "fuzzy issue", "no acceptance criteria")],
        dependency_assumptions=["#2 before #3 — schema (inferred)"],
    )


def test_render_contains_all_sections():
    text = plan_io.render(_plan(), titles={2: "Auth", 3: "Docs", 4: "Typo"})
    assert "# Delivery Plan" in text
    assert "## Batch 1 — proj — Tier 3 critical" in text
    assert "- Issues: #2 Auth" in text
    assert "- Issues: #3 Docs, #4 Typo" in text
    assert "## Needs grooming before sequencing" in text
    assert "#9 fuzzy issue — no acceptance criteria" in text
    assert "## Dependency assumptions" in text


def test_empty_plan_renders_sentinel():
    assert plan_io.render(DeliveryPlan()) == plan_io.EMPTY_SENTINEL + "\n"


def test_status_line_formats():
    done = Batch(1, "t", 1, [1], status=STATUS_DONE, status_detail="https://x/pull/1")
    assert plan_io.status_line(done) == "✅ done — PR: https://x/pull/1"
    awaiting = Batch(1, "t", 3, [1], status=STATUS_AWAITING, status_detail="https://x/pull/2")
    assert "awaiting human approval" in plan_io.status_line(awaiting)
    blocked = Batch(1, "t", 2, [1], status=STATUS_BLOCKED, status_detail="oops")
    assert plan_io.status_line(blocked) == "⚠️ blocked — oops"


def test_write_and_status_roundtrip(tmp_path):
    plan = _plan()
    path = tmp_path / "DELIVERY_PLAN.md"
    plan_io.write_plan(path, plan, titles={2: "Auth", 3: "Docs", 4: "Typo"})
    statuses = plan_io.parse_statuses(path.read_text())
    assert statuses == ["pending", "pending"]

    plan.batches[0].status = STATUS_DONE
    plan.batches[0].status_detail = "https://x/pull/7"
    plan_io.write_plan(path, plan, titles={2: "Auth", 3: "Docs", 4: "Typo"})
    statuses = plan_io.parse_statuses(path.read_text())
    assert statuses[0].startswith("✅ done")


def test_append_summary(tmp_path):
    path = tmp_path / "p.md"
    plan_io.write_plan(path, _plan(), titles={})
    plan_io.append_summary(path, completed=1, awaiting=1, blocked=0, skipped=0)
    text = path.read_text()
    assert "## Execution Summary" in text
    assert "- Completed: 1" in text
