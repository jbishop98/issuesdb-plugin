import pytest

from pilot.cli import _detect_mode, build_parser


def test_detect_mode_ids():
    assert _detect_mode(["1", "2", "3"]) == ("ids", [1, 2, 3])


def test_detect_mode_project():
    assert _detect_mode(["rentaway"]) == ("project", ["rentaway"])


def test_detect_mode_backlog():
    assert _detect_mode([]) == ("backlog", [])


def test_detect_mode_mixed_is_error():
    with pytest.raises(SystemExit):
        _detect_mode(["1", "rentaway"])


def test_help_runs_and_documents_modes(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "input modes:" in out
    assert "ISSUESDB_MCP_SECRET" in out
    assert "--dry-run" in out
    assert "--no-llm" in out


def test_version_flag(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pilot" in out
