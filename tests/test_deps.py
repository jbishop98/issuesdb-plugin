from pilot.deps import explicit_edges, merge_edges, parse_refs
from pilot.models import DepEdge, Issue


def test_parse_refs_extracts_numeric_ids():
    assert parse_refs("blocked by #12 and #34, see #12") == {12, 34}
    assert parse_refs("") == set()
    assert parse_refs(None) == set()


def test_explicit_edges_only_links_present_issues():
    issues = [
        Issue(id=1, title="schema", description="adds field"),
        Issue(id=2, title="feature", description="depends on #1 and #999"),
    ]
    edges = explicit_edges(issues)
    assert DepEdge(before=1, after=2, reason="#2 references #1") in edges
    # #999 is dangling -> ignored
    assert all(e.before != 999 and e.after != 999 for e in edges)


def test_explicit_edges_ignores_self_reference():
    issues = [Issue(id=5, title="x", description="see #5")]
    assert explicit_edges(issues) == []


def test_merge_edges_dedupes_on_pair():
    a = [DepEdge(1, 2, "first")]
    b = [DepEdge(1, 2, "second"), DepEdge(2, 3, "new")]
    merged = merge_edges(a, b)
    pairs = {(e.before, e.after) for e in merged}
    assert pairs == {(1, 2), (2, 3)}
    # first reason wins
    assert next(e for e in merged if (e.before, e.after) == (1, 2)).reason == "first"
