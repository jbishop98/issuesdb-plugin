"""Locate project repos and harvest context notes — pilot step 4c.

Deterministic filesystem work: resolve a project name to a local path and read
any CLAUDE.md so the development pipeline gets oriented.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEV_ROOT = Path("~/dev").expanduser()
CLAUDE_MD_LIMIT = 2000


@dataclass
class ProjectContext:
    project: str
    root: str  # resolved path or "not found"
    notes: str  # CLAUDE.md excerpt or ""


def locate_project_root(project: str, dev_root: Path = DEV_ROOT, cwd: Path | None = None) -> str:
    """Resolve a project name to a local path.

    Order (from agents/pilot.md): exact ~/dev/<project>, then ~/dev/<project>*
    prefix match, then a matching subdirectory of cwd. Returns "not found" if
    nothing matches.
    """
    exact = dev_root / project
    if exact.is_dir():
        return str(exact)

    matches = sorted(p for p in dev_root.glob(f"{project}*") if p.is_dir())
    if matches:
        return str(matches[0])

    cwd = cwd or Path.cwd()
    candidate = cwd / project
    if candidate.is_dir():
        return str(candidate)

    return "not found"


def read_claude_md(root: str) -> str:
    """Read a project's CLAUDE.md (truncated). Empty string if absent."""
    if root == "not found":
        return ""
    path = Path(root) / "CLAUDE.md"
    if not path.is_file():
        return ""
    text = path.read_text(errors="replace").strip()
    if len(text) > CLAUDE_MD_LIMIT:
        text = text[:CLAUDE_MD_LIMIT] + " …(truncated)"
    return text


def collect(project: str, dev_root: Path = DEV_ROOT, cwd: Path | None = None) -> ProjectContext:
    root = locate_project_root(project, dev_root, cwd)
    return ProjectContext(project=project, root=root, notes=read_claude_md(root))
