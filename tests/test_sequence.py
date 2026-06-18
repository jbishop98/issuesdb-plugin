from pilot.models import DepEdge, Issue
from pilot.sequence import MAX_TIER1_BUNDLE, sequence


def _issue(id, tier, project="proj", desc=""):
    return Issue(id=id, title=f"issue {id}", description=desc, project=project, tier=tier)


def test_tier1_same_project_bundles_up_to_cap():
    issues = [_issue(i, 1) for i in range(1, 7)]  # six Tier 1, same project
    batches, _ = sequence(issues, [])
    assert len(batches) == 2
    assert len(batches[0].issue_ids) == MAX_TIER1_BUNDLE
    assert len(batches[1].issue_ids) == 2
    assert all(b.tier == 1 for b in batches)


def test_tier1_different_projects_not_bundled_together():
    issues = [_issue(1, 1, "a"), _issue(2, 1, "b")]
    batches, _ = sequence(issues, [])
    assert len(batches) == 2
    assert {b.issue_ids[0] for b in batches} == {1, 2}


def test_tier2_and_tier3_are_standalone_batches():
    issues = [_issue(1, 2), _issue(2, 3)]
    batches, _ = sequence(issues, [])
    assert all(len(b.issue_ids) == 1 for b in batches)


def test_tier3_surfaced_before_tier1():
    issues = [_issue(1, 1), _issue(2, 3)]
    batches, _ = sequence(issues, [])
    assert batches[0].tier == 3
    assert batches[0].issue_ids == [2]


def test_dependencies_respected_over_tier_priority():
    # #1 is Tier 1 but must ship before Tier 3 #2 (explicit edge).
    issues = [_issue(1, 1), _issue(2, 3)]
    edges = [DepEdge(before=1, after=2, reason="prereq")]
    batches, _ = sequence(issues, edges)
    order = [b.issue_ids[0] for b in batches]
    assert order.index(1) < order.index(2)


def test_cycle_is_reported_as_warning():
    issues = [_issue(1, 2), _issue(2, 2)]
    edges = [DepEdge(1, 2, "a"), DepEdge(2, 1, "b")]
    batches, warnings = sequence(issues, edges)
    assert warnings and "cycle" in warnings[0].lower()
    # both issues still sequenced despite the cycle
    seq_ids = {i for b in batches for i in b.issue_ids}
    assert seq_ids == {1, 2}


def test_excluded_issues_are_dropped():
    keep = _issue(1, 2)
    drop = _issue(2, 2)
    drop.include = False
    batches, _ = sequence([keep, drop], [])
    seq_ids = {i for b in batches for i in b.issue_ids}
    assert seq_ids == {1}


def test_batches_indexed_sequentially():
    issues = [_issue(1, 3), _issue(2, 2), _issue(3, 1)]
    batches, _ = sequence(issues, [])
    assert [b.index for b in batches] == list(range(1, len(batches) + 1))
