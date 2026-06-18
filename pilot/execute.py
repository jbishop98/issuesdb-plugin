"""Batch execution — pilot step 7.

Dispatch is hardcoded to ``/orchestrate``. There is deliberately no
``/work-issuesdb`` code path: the pilot's "never dispatch /work-issuesdb"
guardrail becomes a structural invariant here, not prompt discipline.
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

from .models import (
    STATUS_AWAITING,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    Batch,
    DepEdge,
    DeliveryPlan,
    ExecResult,
    Issue,
)

_PR_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
_BLOCKED_RE = re.compile(r"development blocked", re.IGNORECASE)
_TIER3_RE = re.compile(r"requires human merge approval", re.IGNORECASE)


def parse_signals(output: str) -> ExecResult:
    """Map an /orchestrate run's stdout to a structured outcome.

    Precedence matters: a blocked run never produced a PR; a Tier 3 run produces
    a PR *and* the approval-required message, so it must be checked before the
    plain success case.
    """
    output = output or ""
    pr_match = _PR_URL_RE.search(output)
    pr_url = pr_match.group(0) if pr_match else None

    if _BLOCKED_RE.search(output):
        return ExecResult(status=STATUS_BLOCKED, reason="development blocked by orchestrator")
    if _TIER3_RE.search(output):
        return ExecResult(status=STATUS_AWAITING, pr_url=pr_url, reason="Tier 3 — human approval")
    if pr_url:
        return ExecResult(status=STATUS_DONE, pr_url=pr_url)
    return ExecResult(status=STATUS_FAILED, reason="no PR URL or known signal in output")


def build_context_block(project_root: str, claude_md_notes: str, dep_notes: str,
                        issue_bodies: str = "") -> str:
    """Assemble the context handed to /orchestrate.

    Forwarding ``issue_bodies`` (already fetched during planning) lets the
    downstream pipeline avoid re-fetching them — the token-saving hook.
    """
    lines = [
        "Context from delivery planning:",
        f"- Project root: {project_root or 'not found'}",
        f"- CLAUDE.md notes: {claude_md_notes or 'none'}",
        f"- Dependency notes: {dep_notes or 'none'}",
    ]
    if issue_bodies:
        lines.append("\nIssue details (already fetched — no need to re-fetch):")
        lines.append(issue_bodies)
    return "\n".join(lines)


def dispatch_command(issue_ids: list[int], context: str, dispatch: str = "opencode") -> list[str]:
    """Build the subprocess argv that dispatches /orchestrate for a batch."""
    prompt = "/orchestrate " + " ".join(str(i) for i in issue_ids)
    if context:
        prompt += "\n\n" + context
    if dispatch == "claude":
        return ["claude", "-p", prompt]
    return ["opencode", "run", "--prompt", prompt]


def _batch_predecessors(batches: list[Batch], edges: list[DepEdge]) -> dict[int, set[int]]:
    """Map each batch index to the set of batch indexes it depends on."""
    batch_of: dict[int, int] = {}
    for batch in batches:
        for issue_id in batch.issue_ids:
            batch_of[issue_id] = batch.index
    preds: dict[int, set[int]] = {b.index: set() for b in batches}
    for edge in edges:
        a, b = batch_of.get(edge.before), batch_of.get(edge.after)
        if a is not None and b is not None and a != b:
            preds[b].add(a)
    return preds


def run_batches(
    plan: DeliveryPlan,
    edges: list[DepEdge],
    *,
    dispatch: str = "opencode",
    timeout: int = 3600,
    context_for: Optional[Callable[[Batch], str]] = None,
    runner: Optional[Callable[[list[str], int], str]] = None,
    on_update: Optional[Callable[[Batch], None]] = None,
) -> dict[str, int]:
    """Execute batches in order, mutating their status in place.

    ``runner`` runs the argv and returns combined stdout/stderr (injectable for
    tests). ``on_update`` fires after each batch (e.g. to re-write the plan file
    and post issuesdb updates). Returns summary counts.
    """
    runner = runner or _default_runner
    context_for = context_for or (lambda b: "")
    preds = _batch_predecessors(plan.batches, edges)
    failed_states = {STATUS_BLOCKED, STATUS_FAILED, STATUS_SKIPPED}
    by_index = {b.index: b for b in plan.batches}

    counts = {"completed": 0, "awaiting": 0, "blocked": 0, "skipped": 0}

    for batch in plan.batches:
        bad = [p for p in preds[batch.index] if by_index[p].status in failed_states]
        if bad:
            batch.status = STATUS_SKIPPED
            batch.status_detail = "depends on batch " + ", ".join(str(p) for p in sorted(bad))
            counts["skipped"] += 1
            if on_update:
                on_update(batch)
            continue

        argv = dispatch_command(batch.issue_ids, context_for(batch), dispatch)
        try:
            output = runner(argv, timeout)
        except Exception as exc:  # noqa: BLE001 - any dispatch failure → failed batch
            batch.status = STATUS_FAILED
            batch.status_detail = f"dispatch error: {exc}"
            counts["blocked"] += 1
            if on_update:
                on_update(batch)
            continue

        result = parse_signals(output)
        batch.status = result.status
        batch.status_detail = result.pr_url or result.reason
        if result.status == STATUS_DONE:
            counts["completed"] += 1
        elif result.status == STATUS_AWAITING:
            counts["awaiting"] += 1
        else:
            counts["blocked"] += 1
        if on_update:
            on_update(batch)

    return counts


def _default_runner(argv: list[str], timeout: int) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return (proc.stdout or "") + (proc.stderr or "")


def issue_bodies_for(batch: Batch, issues: dict[int, Issue], limit: int = 4000) -> str:
    """Compact issue bodies to forward into a batch's context block."""
    chunks: list[str] = []
    for issue_id in batch.issue_ids:
        issue = issues.get(issue_id)
        if not issue:
            continue
        body = (issue.description or "").strip()
        if len(body) > limit:
            body = body[:limit] + " …(truncated)"
        chunks.append(f"### #{issue.id} {issue.title}\n{body}")
    return "\n\n".join(chunks)
