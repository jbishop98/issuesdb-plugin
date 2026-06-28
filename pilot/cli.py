"""Command-line entry point for the pilot.

Usage mirrors the original pilot agent's three input modes:
  - one or more issue IDs
  - a single project name
  - no arguments (full backlog)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .context import collect
from .deps import explicit_edges, merge_edges
from .models import (
    STATUS_AWAITING,
    STATUS_DONE,
    Batch,
    DeliveryPlan,
    DepEdge,
    Issue,
)
from .sequence import sequence

EPILOG = """\
input modes:
  pilot 142 143 150        plan & execute specific issue IDs
  pilot rentaway           plan & execute every open/ready issue in a project
  pilot                    plan & execute the full backlog (all projects)

examples:
  pilot rentaway --dry-run            write the delivery plan, do not execute
  pilot 142 --dispatch claude         dispatch via `claude -p` instead of opencode
  pilot --plan-dir ~/plans            write DELIVERY_PLAN-<ts>.md under ~/plans
  pilot rentaway --no-llm --dry-run   offline planning (no API key needed)

environment:
  ISSUESDB_MCP_SECRET   Bearer token for the issuesdb MCP server (required)
  ANTHROPIC_API_KEY     key for API-based planning (only needed with --planner api)
  ISSUESDB_MCP_URL      override the MCP endpoint (optional)
  PILOT_MODEL           override the classifier model (optional)
  PILOT_PLANNER         default planner backend: auto | api | claude (default: auto)

The pilot never edits code or merges. Each batch is dispatched to /orchestrate,
which owns the groom -> triage -> develop -> review -> merge pipeline.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pilot",
        description=(
            "Delivery planner and executor for issuesdb. Loads issues, classifies "
            "risk tiers, maps dependencies, sequences them into ordered delivery "
            "batches, writes a DELIVERY_PLAN, then executes each batch via "
            "/orchestrate."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help="issue IDs (numeric), a single project name, or nothing for the full backlog",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write the delivery plan but do not dispatch any batches",
    )
    parser.add_argument(
        "--dispatch",
        choices=("opencode", "claude"),
        default="opencode",
        help="how to dispatch /orchestrate per batch (default: opencode)",
    )
    parser.add_argument(
        "--plan-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="directory for DELIVERY_PLAN-<timestamp>.md (default: ~/dev)",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Anthropic model for the judgment calls (default: env PILOT_MODEL or claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        metavar="SECONDS",
        help="per-batch dispatch timeout in seconds (default: 3600)",
    )
    parser.add_argument(
        "--planner",
        choices=("auto", "api", "claude"),
        default=None,
        help=(
            "how to run the planning LLM calls. 'api' uses the Anthropic API "
            "(needs ANTHROPIC_API_KEY), 'claude' shells out to claude -p (uses "
            "your subscription, no key needed). 'auto' (default) picks 'api' if "
            "ANTHROPIC_API_KEY is set, otherwise 'claude'."
        ),
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "skip the LLM judgment calls (offline/testing): treat all open issues "
            "as ready, default every issue to Tier 2, infer no dependencies"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _detect_mode(targets: list[str]) -> tuple[str, list]:
    """Return (mode, parsed) where mode is 'ids' | 'project' | 'backlog'."""
    if not targets:
        return "backlog", []
    if all(t.isdigit() for t in targets):
        return "ids", [int(t) for t in targets]
    if len(targets) == 1:
        return "project", [targets[0]]
    raise SystemExit("error: pass either numeric issue IDs, a single project name, or nothing")


def _load_issues(tracker, mode: str, parsed: list) -> list[Issue]:
    if mode == "ids":
        return [tracker.get_issue(i) for i in parsed]
    if mode == "project":
        project = parsed[0]
        issues = tracker.list_issues(project=project, status="open")
        issues += tracker.list_issues(project=project, status="ready")
        return issues
    # backlog: per-project to avoid a global limit truncating results
    issues: list[Issue] = []
    for project in tracker.list_projects():
        issues += tracker.list_issues(project=project, status="open")
        issues += tracker.list_issues(project=project, status="ready")
    return issues


def _plan_from(issues: list[Issue], edges: list[DepEdge], inferred: list[DepEdge],
               warnings: list[str]) -> DeliveryPlan:
    batches, seq_warnings = sequence(issues, edges)
    plan = DeliveryPlan(batches=batches)
    plan.needs_grooming = [
        (i.id, i.title, i.exclude_reason or "needs grooming")
        for i in issues
        if not i.include
    ]
    plan.dependency_assumptions = [
        f"#{e.before} before #{e.after} — {e.reason} (inferred)" for e in inferred
    ]
    plan.dependency_assumptions += warnings + seq_warnings
    return plan


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = Config.from_env()
    config.dry_run = args.dry_run
    config.dispatch = args.dispatch
    config.timeout = args.timeout
    if args.planner:
        config.planner = args.planner
    if args.plan_dir:
        config.plan_dir = args.plan_dir.expanduser()
    if args.model:
        config.model = args.model

    if not config.mcp_secret:
        print("error: ISSUESDB_MCP_SECRET is not set", file=sys.stderr)
        return 2

    mode, parsed = _detect_mode(args.targets)

    from .issuesdb import Tracker

    tracker = Tracker(config.mcp_url, config.mcp_secret)
    issues = _load_issues(tracker, mode, parsed)
    issue_map = {i.id: i for i in issues}

    # Steps 2-4: judgment (or the offline fallback).
    inferred: list[DepEdge] = []
    if args.no_llm:
        for i in issues:
            i.tier = i.tier or 2
            i.include = True
    else:
        classifier = _make_classifier(config)
        result = classifier.plan_all(issues)
        for i in issues:
            include, needs, reason = result.readiness.get(i.id, (True, False, ""))
            i.include, i.needs_grooming = include, needs
            if not include:
                i.exclude_reason = reason
            tier, _reason = result.tiers.get(i.id, (2, ""))
            i.tier = tier
        inferred = result.deps

    included = [i for i in issues if i.include]
    edges = merge_edges(explicit_edges(included), inferred)

    plan = _plan_from(issues, edges, inferred, warnings=[])

    from . import plan_io

    titles = {i.id: i.title for i in issues}
    plan_path = config.plan_path()
    plan_io.write_plan(plan_path, plan, titles)

    if plan.is_empty:
        print(f"No actionable issues. Plan written to {plan_path}")
        return 0

    if config.dry_run:
        print(f"Dry run — plan written to {plan_path} ({len(plan.batches)} batches)")
        return 0

    _execute(plan, edges, config, tracker, issue_map, titles, plan_path)
    print(f"Execution complete. Plan: {plan_path}")
    return 0


def run_console() -> None:
    """Console-script entry point (see pyproject [project.scripts])."""
    raise SystemExit(run())


def _make_classifier(config: Config):
    from .classify import ApiBackend, ClaudeCliBackend, Classifier

    planner = config.planner
    if planner == "auto":
        planner = "api" if config.anthropic_api_key else "claude"
    if planner == "claude":
        backend = ClaudeCliBackend(model=config.model, timeout=config.timeout)
        return Classifier(backend)
    return Classifier(ApiBackend(config.anthropic_api_key, config.model))


def _execute(plan, edges, config, tracker, issue_map, titles, plan_path) -> None:
    from . import plan_io
    from .context import ProjectContext
    from .execute import build_context_block, issue_bodies_for, run_batches

    ctx_cache: dict[str, ProjectContext] = {}

    def context_for(batch: Batch) -> str:
        first = issue_map.get(batch.issue_ids[0])
        project = first.project if first else ""
        if project not in ctx_cache:
            ctx_cache[project] = collect(project)
        pc = ctx_cache[project]
        return build_context_block(
            project_root=pc.root,
            claude_md_notes=pc.notes,
            dep_notes=batch.rationale,
            issue_bodies=issue_bodies_for(batch, issue_map),
        )

    def on_update(batch: Batch) -> None:
        plan_io.write_plan(plan_path, plan, titles)
        if batch.status in (STATUS_DONE, STATUS_AWAITING) and batch.status_detail.startswith("http"):
            for issue_id in batch.issue_ids:
                try:
                    tracker.update_issue(issue_id, pull_request=batch.status_detail)
                except Exception:  # noqa: BLE001 - status update is best-effort
                    pass

    counts = run_batches(
        plan,
        edges,
        dispatch=config.dispatch,
        timeout=config.timeout,
        context_for=context_for,
        runner=None,
        on_update=on_update,
    )
    plan_io.append_summary(
        plan_path,
        completed=counts["completed"],
        awaiting=counts["awaiting"],
        blocked=counts["blocked"],
        skipped=counts["skipped"],
    )
