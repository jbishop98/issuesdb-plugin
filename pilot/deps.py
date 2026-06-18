"""Dependency parsing — the deterministic half of pilot step 4.

Explicit ``#123`` references are extracted with a regex here. The *structural*
inference half (schema-before-feature, auth-before-gated, etc.) is a judgment
call and lives in classify.py.
"""

from __future__ import annotations

import re

from .models import DepEdge, Issue

_REF_RE = re.compile(r"#(\d+)")


def parse_refs(text: str) -> set[int]:
    """Return all ``#123`` issue references found in a block of text."""
    return {int(m) for m in _REF_RE.findall(text or "")}


def explicit_edges(issues: list[Issue]) -> list[DepEdge]:
    """Derive dependency edges from explicit ``#123`` refs in descriptions.

    A reference from issue A to issue B is read as "A depends on B" — B must
    ship before A. Only references to issues present in ``issues`` are kept;
    self-references and dangling refs are ignored.
    """
    ids = {issue.id for issue in issues}
    edges: list[DepEdge] = []
    for issue in issues:
        for ref in parse_refs(issue.description):
            if ref in ids and ref != issue.id:
                edges.append(
                    DepEdge(before=ref, after=issue.id, reason=f"#{issue.id} references #{ref}")
                )
    return edges


def merge_edges(*edge_lists: list[DepEdge]) -> list[DepEdge]:
    """Combine edge lists, de-duplicating on (before, after) and keeping the
    first reason seen for each pair."""
    seen: dict[tuple[int, int], DepEdge] = {}
    for edges in edge_lists:
        for edge in edges:
            key = (edge.before, edge.after)
            if key not in seen:
                seen[key] = edge
    return list(seen.values())
