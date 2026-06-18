"""Deterministic batch sequencing — pilot step 5.

Pure functions, no I/O. This is where the reliability payoff lives: given the
same issues + dependency edges, sequencing is fully reproducible and unit
testable.

Ordering rules (from agents/pilot.md):
  1. Respect dependencies — a prerequisite ships before its dependents.
  2. Surface Tier 3 items early (de-risk before building on top of them).
  3. Bundle Tier 1 items together (<=4 per batch, same project).
  4. Aim for a coherent theme per batch (same project).
Tier 2 and Tier 3 issues are never bundled — one issue per batch.
"""

from __future__ import annotations

from .models import Batch, DepEdge, Issue

MAX_TIER1_BUNDLE = 4

_TIER_LABEL = {1: "Tier 1 cleanup", 2: "Tier 2 work", 3: "Tier 3 critical"}


def _toposort(issues: list[Issue], edges: list[DepEdge]) -> tuple[list[Issue], list[str]]:
    """Kahn's algorithm with a deterministic priority tie-break.

    Among issues whose prerequisites are already placed, pick by:
      (-tier, project, id) — highest tier first (Tier 3 early), then grouped by
      project for coherent themes, then id for stability.

    Returns (ordered_issues, warnings). Any issues left over from a dependency
    cycle are appended in id order and reported as a warning.
    """
    by_id = {issue.id: issue for issue in issues}
    indegree = {issue.id: 0 for issue in issues}
    successors: dict[int, list[int]] = {issue.id: [] for issue in issues}

    for edge in edges:
        if edge.before in by_id and edge.after in by_id:
            indegree[edge.after] += 1
            successors[edge.before].append(edge.after)

    def sort_key(issue_id: int):
        issue = by_id[issue_id]
        return (-(issue.tier or 0), issue.project, issue.id)

    ready = sorted([i for i in indegree if indegree[i] == 0], key=sort_key)
    ordered: list[Issue] = []
    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for nxt in successors[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=sort_key)

    warnings: list[str] = []
    if len(ordered) < len(issues):
        placed = {issue.id for issue in ordered}
        leftover = sorted(i for i in by_id if i not in placed)
        warnings.append(
            "dependency cycle detected among issues "
            + ", ".join(f"#{i}" for i in leftover)
            + " — sequenced in id order, ordering unconfirmed"
        )
        ordered.extend(by_id[i] for i in leftover)

    return ordered, warnings


def _theme(project: str, tier: int) -> str:
    label = _TIER_LABEL.get(tier, f"Tier {tier} work")
    return f"{project} — {label}" if project else label


def sequence(issues: list[Issue], edges: list[DepEdge]) -> tuple[list[Batch], list[str]]:
    """Sequence included issues into ordered delivery batches.

    Returns (batches, warnings). ``warnings`` carries any dependency-cycle notes
    for the plan's "Dependency assumptions" section.
    """
    actionable = [i for i in issues if i.include]
    ordered, warnings = _toposort(actionable, edges)

    batches: list[Batch] = []
    current: list[Issue] = []  # an accumulating Tier 1 bundle

    def flush() -> None:
        if not current:
            return
        ids = [i.id for i in current]
        batches.append(
            Batch(
                index=len(batches) + 1,
                theme=_theme(current[0].project, 1),
                tier=1,
                issue_ids=ids,
                rationale="Bundled Tier 1 items in the same project.",
            )
        )
        current.clear()

    for issue in ordered:
        tier = issue.tier or 2
        if tier == 1:
            # Bundle with the run-in-progress only if same project and under cap.
            if current and (
                current[0].project != issue.project or len(current) >= MAX_TIER1_BUNDLE
            ):
                flush()
            current.append(issue)
        else:
            flush()
            rationale = (
                "Surfaced early to de-risk downstream work."
                if tier == 3
                else "Standalone delivery."
            )
            batches.append(
                Batch(
                    index=len(batches) + 1,
                    theme=_theme(issue.project, tier),
                    tier=tier,
                    issue_ids=[issue.id],
                    rationale=rationale,
                )
            )
    flush()

    # Reindex defensively so indexes are always 1..N in execution order.
    for n, batch in enumerate(batches, start=1):
        batch.index = n

    return batches, warnings
