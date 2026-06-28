"""Tests for classify.py — backends, parsing, and the combined schema."""

import json

import pytest

from pilot.classify import (
    ClaudeCliBackend,
    Classifier,
    PlanResult,
    _extract_json_object,
    _parse_claude_output,
    _parse_combined,
)
from pilot.models import DepEdge, Issue

SAMPLE_ISSUES = [
    Issue(id=1, title="Fix typo in README", project="acme", description="small typo"),
    Issue(id=2, title="Add OAuth flow", project="acme", description="OAuth2 PKCE"),
    Issue(id=3, title="Upgrade deps", project="acme", description="bump versions"),
]

VALID_COMBINED = {
    "readiness": [
        {"id": 1, "include": True, "needs_grooming": False, "reason": "clear"},
        {"id": 2, "include": True, "needs_grooming": True, "reason": "scope unclear"},
        {"id": 3, "include": False, "needs_grooming": True, "reason": "which deps?"},
    ],
    "tiers": [
        {"id": 1, "tier": 1, "reason": "cosmetic"},
        {"id": 2, "tier": 3, "reason": "auth"},
        {"id": 3, "tier": 2, "reason": "default"},
    ],
    "dependencies": [
        {"before": 2, "after": 1, "reason": "auth first"},
    ],
}


# --- _parse_combined -------------------------------------------------------

class TestParseCombined:
    def test_basic(self):
        ids = {1, 2, 3}
        r = _parse_combined(VALID_COMBINED, ids)
        assert isinstance(r, PlanResult)
        assert r.readiness[1] == (True, False, "clear")
        assert r.readiness[3] == (False, True, "which deps?")
        assert r.tiers[2] == (3, "auth")
        assert len(r.deps) == 1
        assert r.deps[0] == DepEdge(before=2, after=1, reason="auth first")

    def test_clamps_invalid_tier(self):
        raw = {
            "readiness": [{"id": 1, "include": True, "needs_grooming": False, "reason": "ok"}],
            "tiers": [{"id": 1, "tier": 99, "reason": "bogus"}],
            "dependencies": [],
        }
        r = _parse_combined(raw, {1})
        assert r.tiers[1][0] == 2  # clamped to default

    def test_filters_dangling_deps(self):
        raw = {
            "readiness": [],
            "tiers": [],
            "dependencies": [{"before": 999, "after": 1, "reason": "ghost"}],
        }
        r = _parse_combined(raw, {1, 2})
        assert r.deps == []

    def test_filters_self_deps(self):
        raw = {
            "readiness": [],
            "tiers": [],
            "dependencies": [{"before": 1, "after": 1, "reason": "self"}],
        }
        r = _parse_combined(raw, {1})
        assert r.deps == []

    def test_empty_sections(self):
        r = _parse_combined({"readiness": [], "tiers": [], "dependencies": []}, set())
        assert r.readiness == {}
        assert r.tiers == {}
        assert r.deps == []


# --- _extract_json_object --------------------------------------------------

class TestExtractJsonObject:
    def test_clean_json(self):
        obj = {"a": 1}
        assert _extract_json_object(json.dumps(obj)) == obj

    def test_with_markdown_fences(self):
        text = '```json\n{"a": 1}\n```'
        assert _extract_json_object(text) == {"a": 1}

    def test_with_surrounding_prose(self):
        text = 'Here is the result:\n{"a": 1}\nDone.'
        assert _extract_json_object(text) == {"a": 1}

    def test_nested_braces(self):
        obj = {"outer": {"inner": [1, 2]}}
        assert _extract_json_object(json.dumps(obj)) == obj

    def test_braces_inside_strings(self):
        obj = {"msg": "use {x} and {y}"}
        assert _extract_json_object(json.dumps(obj)) == obj

    def test_no_json_raises(self):
        with pytest.raises(RuntimeError, match="no JSON object"):
            _extract_json_object("no json here")

    def test_unbalanced_raises(self):
        with pytest.raises(RuntimeError, match="unbalanced"):
            _extract_json_object('{"a": 1')


# --- _parse_claude_output -------------------------------------------------

class TestParseClaudeOutput:
    def test_envelope_with_result(self):
        envelope = {"result": json.dumps({"a": 1}), "type": "result"}
        assert _parse_claude_output(json.dumps(envelope)) == {"a": 1}

    def test_envelope_result_with_fences(self):
        inner = '```json\n{"a": 1}\n```'
        envelope = {"result": inner, "type": "result"}
        assert _parse_claude_output(json.dumps(envelope)) == {"a": 1}

    def test_raw_json_no_envelope(self):
        assert _parse_claude_output('{"a": 1}') == {"a": 1}

    def test_raw_non_json(self):
        with pytest.raises(RuntimeError):
            _parse_claude_output("garbage")


# --- ClaudeCliBackend (mocked subprocess) ----------------------------------

class TestClaudeCliBackend:
    def test_plan_all_empty_issues(self):
        backend = ClaudeCliBackend()
        r = backend.plan_all([])
        assert r.readiness == {}

    def test_plan_all_parses_subprocess(self, monkeypatch):
        envelope = json.dumps({
            "type": "result",
            "result": json.dumps(VALID_COMBINED),
        })

        class FakeProc:
            returncode = 0
            stdout = envelope
            stderr = ""

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        backend = ClaudeCliBackend()
        r = backend.plan_all(SAMPLE_ISSUES)
        assert r.readiness[1] == (True, False, "clear")
        assert r.tiers[2] == (3, "auth")
        assert len(r.deps) == 1

    def test_plan_all_subprocess_failure(self, monkeypatch):
        class FailProc:
            returncode = 1
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FailProc())
        backend = ClaudeCliBackend()
        with pytest.raises(RuntimeError, match="boom"):
            backend.plan_all(SAMPLE_ISSUES)

    def test_argv_includes_model(self, monkeypatch):
        captured = {}
        envelope = json.dumps({"result": json.dumps(VALID_COMBINED)})

        class FakeProc:
            returncode = 0
            stdout = envelope
            stderr = ""

        def capture_run(*a, **kw):
            captured["argv"] = a[0]
            return FakeProc()

        monkeypatch.setattr("subprocess.run", capture_run)
        backend = ClaudeCliBackend(model="claude-haiku-4-5-20251001")
        backend.plan_all(SAMPLE_ISSUES)
        assert "--model" in captured["argv"]
        assert "claude-haiku-4-5-20251001" in captured["argv"]


# --- Classifier wrapper ----------------------------------------------------

class TestClassifier:
    def test_delegates_to_backend(self, monkeypatch):
        envelope = json.dumps({"result": json.dumps(VALID_COMBINED)})

        class FakeProc:
            returncode = 0
            stdout = envelope
            stderr = ""

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        c = Classifier(ClaudeCliBackend())
        r = c.plan_all(SAMPLE_ISSUES)
        assert 1 in r.readiness
        assert 2 in r.tiers
