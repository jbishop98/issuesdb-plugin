"""Render, write, and read back DELIVERY_PLAN.md — pilot step 6 and step 7 updates.

The on-disk format is the contract from agents/pilot.md. execute.py mutates the
in-memory DeliveryPlan and re-renders the whole file after each batch, so the
file always reflects current state.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import (
    STATUS_AWAITING,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    Batch,
    DeliveryPlan,
)

EMPTY_SENTINEL = "No actionable issues at this time."


def status_line(batch: Batch) -> str:
    """Render a batch's Status: line in the documented display format."""
    detail = batch.status_detail
    if batch.status == STATUS_PENDING:
        return "pending"
    if batch.status == STATUS_DONE:
        return f"✅ done — PR: {detail or 'n/a'}"
    if batch.status == STATUS_AWAITING:
        return f"⏳ awaiting human approval — PR: {detail or 'n/a'}"
    if batch.status == STATUS_BLOCKED:
        return f"⚠️ blocked — {detail or 'no reason given'}"
    if batch.status == STATUS_FAILED:
        return f"❌ failed — {detail or 'no reason given'}"
    if batch.status == STATUS_SKIPPED:
        return f"⏭ skipped — {detail or 'dependency not met'}"
    return batch.status


def _issue_list(batch: Batch, titles: dict[int, str]) -> str:
    return ", ".join(f"#{i} {titles.get(i, '').strip()}".rstrip() for i in batch.issue_ids)


def render(plan: DeliveryPlan, titles: dict[int, str] | None = None) -> str:
    """Render the full DELIVERY_PLAN.md text."""
    titles = titles or {}
    if plan.is_empty:
        return EMPTY_SENTINEL + "\n"

    out: list[str] = ["# Delivery Plan", ""]
    for batch in plan.batches:
        out.append(f"## Batch {batch.index} — {batch.theme}")
        out.append(f"- Tier: {batch.tier}")
        out.append(f"- Issues: {_issue_list(batch, titles)}")
        out.append(f"- Rationale: {batch.rationale}")
        out.append(f"- Status: {status_line(batch)}")
        out.append("")

    if plan.needs_grooming:
        out.append("## Needs grooming before sequencing")
        for issue_id, title, missing in plan.needs_grooming:
            out.append(f"- #{issue_id} {title} — {missing}")
        out.append("")

    if plan.dependency_assumptions:
        out.append("## Dependency assumptions")
        for note in plan.dependency_assumptions:
            out.append(f"- {note}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def write_plan(path: str | Path, plan: DeliveryPlan, titles: dict[int, str] | None = None) -> Path:
    """Write the plan to ``path``, creating parent dirs and overwriting."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(plan, titles))
    return path


def append_summary(path: str | Path, completed: int, awaiting: int, blocked: int, skipped: int,
                   next_actions: str = "none") -> None:
    """Append the Execution Summary block after all batches run (step 7)."""
    path = Path(path).expanduser()
    block = (
        "\n## Execution Summary\n"
        f"- Completed: {completed}\n"
        f"- Awaiting approval: {awaiting} (Tier 3 — human merge required)\n"
        f"- Blocked/failed: {blocked}\n"
        f"- Skipped: {skipped}\n"
        f"- Next actions: {next_actions}\n"
    )
    with path.open("a") as f:
        f.write(block)


_STATUS_RE = re.compile(r"^- Status: (.+)$", re.MULTILINE)


def parse_statuses(text: str) -> list[str]:
    """Read back every Status: line — used by the round-trip tests."""
    return _STATUS_RE.findall(text)
