"""Core data structures shared across the pilot pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Batch status markers written into DELIVERY_PLAN.md. These strings are part of
# the file contract — execute.py and plan_io.py both depend on them.
STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_AWAITING = "awaiting-approval"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class Issue:
    """A single issuesdb issue, enriched as it moves through planning."""

    id: int
    title: str
    description: str = ""
    status: str = "open"
    project: str = ""
    # Filled in during planning:
    tier: Optional[int] = None  # 1 | 2 | 3
    include: bool = True  # excluded issues never make it into a batch
    needs_grooming: bool = False
    exclude_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Issue":
        """Build an Issue from a raw issuesdb record, tolerating missing keys."""
        return cls(
            id=int(data["id"]),
            title=data.get("title", ""),
            description=data.get("description") or data.get("body", "") or "",
            status=data.get("status", "open"),
            project=data.get("project", ""),
        )


@dataclass(frozen=True)
class DepEdge:
    """A directed dependency: ``before`` must ship before ``after``."""

    before: int
    after: int
    reason: str = ""


@dataclass
class Batch:
    """An ordered unit of delivery dispatched to /orchestrate as one PR."""

    index: int
    theme: str
    tier: int
    issue_ids: list[int]
    rationale: str = ""
    status: str = STATUS_PENDING
    status_detail: str = ""  # e.g. PR url or blocked reason


@dataclass
class DeliveryPlan:
    """The full plan: batches plus the two informational sections."""

    batches: list[Batch] = field(default_factory=list)
    needs_grooming: list[tuple[int, str, str]] = field(default_factory=list)
    # (issue_id, title, what's missing)
    dependency_assumptions: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.batches


@dataclass
class ExecResult:
    """Parsed outcome of dispatching one batch to /orchestrate."""

    status: str  # STATUS_DONE | STATUS_AWAITING | STATUS_BLOCKED | STATUS_FAILED
    pr_url: Optional[str] = None
    reason: str = ""
