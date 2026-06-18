"""The three LLM judgment calls — pilot steps 2, 3, and the inference half of 4.

Each call uses the Anthropic Messages API with a forced tool call, so the model
must return schema-valid JSON (tier in {1,2,3}, etc.) at temperature 0. The
canonical tier table is read from commands/triage-issue.md at runtime rather
than hardcoded, so it cannot drift from the source of truth.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import DepEdge, Issue

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TRIAGE_SKILL = PLUGIN_ROOT / "commands" / "triage-issue.md"

_FALLBACK_TIER_TABLE = (
    "Tier 1 — Docs, typos, copy/cosmetic, simple config.\n"
    "Tier 2 — Bug fixes, new features in non-critical paths.\n"
    "Tier 3 — Auth, security, data integrity, API contracts, schema changes, "
    "perf-critical paths."
)


@lru_cache(maxsize=1)
def tier_table() -> str:
    """Canonical tier definitions, quoted from the triage-issue skill."""
    try:
        return TRIAGE_SKILL.read_text()
    except OSError:
        return _FALLBACK_TIER_TABLE


class Classifier:
    """Wraps the Anthropic client. Construct once, reuse across calls."""

    def __init__(self, api_key: str, model: str):
        try:
            import anthropic  # lazy: only needed when actually classifying
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'anthropic' package is required for classification. "
                "Install it with: pip install anthropic"
            ) from exc
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set — required for classification.")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _call(self, system: str, user: str, tool: dict) -> dict:
        """Single forced-tool call; returns the tool input dict."""
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            temperature=0,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user}],
        )
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("model did not return the expected tool call")

    # --- step 3: tier classification --------------------------------------
    def classify_tiers(self, issues: list[Issue]) -> dict[int, tuple[int, str]]:
        if not issues:
            return {}
        tool = {
            "name": "report_tiers",
            "description": "Report the risk tier for each issue.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "tier": {"type": "integer", "enum": [1, 2, 3]},
                                "reason": {"type": "string"},
                            },
                            "required": ["id", "tier", "reason"],
                        },
                    }
                },
                "required": ["issues"],
            },
        }
        system = (
            "You classify software issues into risk tiers. Use this canonical "
            "tier table as the source of truth:\n\n" + tier_table() + "\n\n"
            "When in doubt, go one tier higher. If an issue touches auth, user "
            "data, payments, or external APIs anywhere in its call graph, use Tier 3."
        )
        user = "Classify these issues:\n\n" + _issues_blob(issues)
        out = self._call(system, user, tool)
        return {int(r["id"]): (int(r["tier"]), r.get("reason", "")) for r in out["issues"]}

    # --- step 2: grooming-readiness ---------------------------------------
    def assess_readiness(self, issues: list[Issue]) -> dict[int, tuple[bool, bool, str]]:
        if not issues:
            return {}
        tool = {
            "name": "report_readiness",
            "description": "Judge whether each open issue is clear enough to sequence.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "include": {"type": "boolean"},
                                "needs_grooming": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["id", "include", "needs_grooming", "reason"],
                        },
                    }
                },
                "required": ["issues"],
            },
        }
        system = (
            "For each open issue, judge from the description alone whether there "
            "is enough clarity to classify and sequence it (problem is clear, some "
            "direction exists). If yes, set include=true; flag needs_grooming=true "
            "if it is includable but still fuzzy. If there is not enough to act on, "
            "set include=false and needs_grooming=true with a one-line reason of "
            "what is missing."
        )
        user = "Assess these open issues:\n\n" + _issues_blob(issues)
        out = self._call(system, user, tool)
        return {
            int(r["id"]): (bool(r["include"]), bool(r["needs_grooming"]), r.get("reason", ""))
            for r in out["issues"]
        }

    # --- step 4b: structural dependency inference -------------------------
    def infer_dependencies(self, issues: list[Issue]) -> list[DepEdge]:
        if len(issues) < 2:
            return []
        tool = {
            "name": "report_dependencies",
            "description": "Report structural ordering dependencies between issues.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "before": {"type": "integer"},
                                "after": {"type": "integer"},
                                "reason": {"type": "string"},
                            },
                            "required": ["before", "after", "reason"],
                        },
                    }
                },
                "required": ["edges"],
            },
        }
        system = (
            "Infer structural delivery dependencies between issues: schema changes "
            "before features consuming new fields; auth changes before features "
            "gated on them; shared infrastructure before downstream consumers. "
            "'before' must ship before 'after'. Only report dependencies you are "
            "confident about; do not invent them. Use only the given issue ids."
        )
        user = "Infer ordering dependencies among these issues:\n\n" + _issues_blob(issues)
        out = self._call(system, user, tool)
        ids = {i.id for i in issues}
        edges: list[DepEdge] = []
        for e in out["edges"]:
            b, a = int(e["before"]), int(e["after"])
            if b in ids and a in ids and b != a:
                edges.append(DepEdge(before=b, after=a, reason=e.get("reason", "")))
        return edges


def _issues_blob(issues: list[Issue]) -> str:
    rows = [
        {"id": i.id, "title": i.title, "project": i.project, "description": i.description}
        for i in issues
    ]
    return json.dumps(rows, indent=2)
