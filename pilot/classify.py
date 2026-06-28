"""LLM judgment calls — pilot steps 2, 3, and the inference half of 4.

Two backends:
  - ApiBackend: direct Anthropic Messages API with forced tool calls (needs
    ANTHROPIC_API_KEY, metered per-token, schema-guaranteed via tool_choice).
  - ClaudeCliBackend: shells out to `claude -p` and rides the user's
    subscription — no API key needed.  Collapses all three planning calls
    into a single prompt for efficiency.

The canonical tier table is read from commands/triage-issue.md at runtime
rather than hardcoded, so it cannot drift from the source of truth.
"""

from __future__ import annotations

import json
import subprocess
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

COMBINED_SCHEMA = {
    "type": "object",
    "properties": {
        "readiness": {
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
        },
        "tiers": {
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
        },
        "dependencies": {
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
        },
    },
    "required": ["readiness", "tiers", "dependencies"],
}

_COMBINED_SYSTEM = """\
You are a delivery planner for a software issue tracker. Given a list of open
issues, perform ALL THREE of the following analyses in a single response:

1. READINESS — for each issue, judge from the description alone whether there
   is enough clarity to classify and sequence it. Set include=true if the
   problem is clear and some direction exists. Flag needs_grooming=true if it
   is includable but still fuzzy. If there is not enough to act on, set
   include=false and needs_grooming=true with a one-line reason of what is
   missing.

2. TIERS — for each issue you marked include=true, classify its risk tier
   using this canonical tier table:

{tier_table}

   When in doubt, go one tier higher. If an issue touches auth, user data,
   payments, or external APIs anywhere in its call graph, use Tier 3.
   For issues marked include=false, still assign a tier (your best guess).

3. DEPENDENCIES — infer structural delivery dependencies between the
   included issues: schema changes before features consuming new fields;
   auth changes before features gated on them; shared infrastructure before
   downstream consumers. "before" must ship before "after". Only report
   dependencies you are confident about; do not invent them. Use only the
   given issue ids. If there are fewer than 2 included issues, return an
   empty array."""


@lru_cache(maxsize=1)
def tier_table() -> str:
    try:
        return TRIAGE_SKILL.read_text()
    except OSError:
        return _FALLBACK_TIER_TABLE


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

class PlanResult:
    """Combined output from the three planning judgments."""

    __slots__ = ("readiness", "tiers", "deps")

    def __init__(
        self,
        readiness: dict[int, tuple[bool, bool, str]],
        tiers: dict[int, tuple[int, str]],
        deps: list[DepEdge],
    ):
        self.readiness = readiness
        self.tiers = tiers
        self.deps = deps


def _parse_combined(raw: dict, issue_ids: set[int]) -> PlanResult:
    """Parse the combined schema into a PlanResult."""
    readiness: dict[int, tuple[bool, bool, str]] = {}
    for r in raw.get("readiness", []):
        readiness[int(r["id"])] = (
            bool(r["include"]),
            bool(r["needs_grooming"]),
            r.get("reason", ""),
        )

    tiers: dict[int, tuple[int, str]] = {}
    for r in raw.get("tiers", []):
        t = int(r["tier"])
        if t not in (1, 2, 3):
            t = 2
        tiers[int(r["id"])] = (t, r.get("reason", ""))

    deps: list[DepEdge] = []
    for e in raw.get("dependencies", []):
        b, a = int(e["before"]), int(e["after"])
        if b in issue_ids and a in issue_ids and b != a:
            deps.append(DepEdge(before=b, after=a, reason=e.get("reason", "")))

    return PlanResult(readiness=readiness, tiers=tiers, deps=deps)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class ApiBackend:
    """Metered Anthropic Messages API with forced tool calls."""

    def __init__(self, api_key: str, model: str):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'anthropic' package is required. "
                "Install it with: pip install anthropic"
            ) from exc
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — use --planner claude "
                "to plan via your subscription instead."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _call(self, system: str, user: str, tool: dict) -> dict:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
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

    def plan_all(self, issues: list[Issue]) -> PlanResult:
        if not issues:
            return PlanResult({}, {}, [])
        tool = {
            "name": "report_plan",
            "description": "Report readiness, tiers, and dependencies for all issues.",
            "input_schema": COMBINED_SCHEMA,
        }
        system = _COMBINED_SYSTEM.format(tier_table=tier_table())
        user = "Analyse these issues:\n\n" + _issues_blob(issues)
        raw = self._call(system, user, tool)
        return _parse_combined(raw, {i.id for i in issues})


class ClaudeCliBackend:
    """Subscription-backed planning via ``claude -p`` — no API key."""

    def __init__(self, model: str = "", timeout: int = 120, binary: str = "claude"):
        self._model = model
        self._timeout = timeout
        self._bin = binary

    def plan_all(self, issues: list[Issue]) -> PlanResult:
        if not issues:
            return PlanResult({}, {}, [])
        schema_str = json.dumps(COMBINED_SCHEMA, indent=2)
        system = _COMBINED_SYSTEM.format(tier_table=tier_table())
        prompt = (
            f"{system}\n\n"
            f"Analyse these issues:\n\n{_issues_blob(issues)}\n\n"
            "Respond with ONLY a JSON object matching this schema — no prose, "
            "no markdown fences, no explanation:\n\n" + schema_str
        )
        argv = [self._bin, "-p", prompt, "--output-format", "json"]
        if self._model:
            argv += ["--model", self._model]
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=self._timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"{self._bin} failed (exit {proc.returncode}): "
                + (proc.stderr or proc.stdout or "").strip()[:300]
            )
        raw = _parse_claude_output(proc.stdout)
        return _parse_combined(raw, {i.id for i in issues})


def _parse_claude_output(stdout: str) -> dict:
    """Extract the JSON object from ``claude -p --output-format json`` output.

    The envelope is ``{"result": "<text>", ...}``. The text may contain
    markdown fences or surrounding prose — we extract the outermost ``{…}``.
    """
    try:
        envelope = json.loads(stdout)
        text = envelope.get("result", stdout)
    except json.JSONDecodeError:
        text = stdout

    return _extract_json_object(text)


def _extract_json_object(text: str) -> dict:
    """Pull the outermost JSON object from text, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = []
        for line in lines[1:]:
            if line.strip() == "```":
                break
            inner.append(line)
        text = "\n".join(inner).strip()
    start = text.find("{")
    if start == -1:
        raise RuntimeError(f"no JSON object in output: {text[:200]}")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise RuntimeError(f"unbalanced braces in output: {text[:200]}")


# ---------------------------------------------------------------------------
# Classifier (thin wrapper — delegates to a backend)
# ---------------------------------------------------------------------------

class Classifier:
    """Construct with a backend, then call plan_all()."""

    def __init__(self, backend: ApiBackend | ClaudeCliBackend):
        self._backend = backend

    def plan_all(self, issues: list[Issue]) -> PlanResult:
        return self._backend.plan_all(issues)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issues_blob(issues: list[Issue]) -> str:
    rows = [
        {"id": i.id, "title": i.title, "project": i.project, "description": i.description}
        for i in issues
    ]
    return json.dumps(rows, indent=2)
