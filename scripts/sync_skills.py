#!/usr/bin/env python3
"""Sync issuesdb-plugin commands to skill definitions.

Reads .md files from commands/ and writes them as SKILL.md files under
the specified target directory, converting frontmatter as needed.

Usage:
    python scripts/sync_skills.py [--dry-run] [--delete-removed] [--target target] [--source source]
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent
COMMANDS_DIR = PLUGIN_DIR / "commands"
PLUGIN_SKILLS_DIR = PLUGIN_DIR / "skills"
DEFAULT_SKILLS_DIR = Path.home() / ".claude" / "skills"
ANTIGRAVITY_SKILLS_DIR = Path.home() / ".gemini" / "antigravity" / "skills"
OPENCODE_SKILLS_DIR = Path.home() / ".config" / "opencode" / "skills"

# Agents are authored once in agents/ (Claude Code format) and fan out to each
# platform's agent directory. Claude Code and Antigravity share the flat
# `tools` allowlist format; OpenCode needs a `permission` map + full model id.
AGENTS_DIR = PLUGIN_DIR / "agents"
PLUGIN_AGENTS_DIR = AGENTS_DIR
DEFAULT_AGENTS_DIR = Path.home() / ".claude" / "agents"
ANTIGRAVITY_AGENTS_DIR = Path.home() / ".gemini" / "antigravity" / "agents"
OPENCODE_AGENTS_DIR = Path.home() / ".config" / "opencode" / "agent"

# Claude Code accepts model aliases; OpenCode wants a provider-qualified id.
MODEL_ALIAS_TO_OPENCODE = {
    "sonnet": "anthropic/claude-sonnet-4-20250514",
    "opus": "anthropic/claude-opus-4-20250514",
    "haiku": "anthropic/claude-haiku-4-20250514",
}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (fields, body) split from a markdown file."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    fields: dict[str, str] = {}
    current_key = None
    current_val_lines: list[str] = []

    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if kv:
            if current_key:
                fields[current_key] = " ".join(current_val_lines).strip()
            current_key = kv.group(1)
            current_val_lines = [kv.group(2)]
        elif current_key and line.startswith(" "):
            current_val_lines.append(line.strip())

    if current_key:
        fields[current_key] = " ".join(current_val_lines).strip()

    body = text[m.end():]
    return fields, body


def build_skill_frontmatter(name: str, description: str) -> str:
    if "\n" in description or len(description) > 80:
        # Use block scalar for long descriptions
        indented = "\n  ".join(description.splitlines())
        return f"---\nname: {name}\ndescription: >\n  {indented}\n---\n"
    return f"---\nname: {name}\ndescription: {description}\n---\n"


def build_opencode_agent(fields: dict[str, str], body: str) -> str:
    """Convert a Claude Code agent (flat `tools` allowlist) into an OpenCode
    subagent definition (`permission` map + provider-qualified model)."""
    description = fields.get("description", "").strip()
    tools = {t.strip() for t in fields.get("tools", "").split(",") if t.strip()}

    alias = fields.get("model", "sonnet").strip() or "sonnet"
    model = MODEL_ALIAS_TO_OPENCODE.get(alias, alias)

    lines = ["---", f"description: {description}", "mode: subagent", f"model: {model}"]

    # Map the flat allowlist onto OpenCode's permission keys. Anything not
    # granted in the source is denied. Bash is constrained to read-only git so
    # read-only agents that carry Bash (for `git log`/`git diff`) stay read-only.
    lines.append("permission:")
    lines.append(f"  read: {'allow' if 'Read' in tools else 'deny'}")
    lines.append(f"  edit: {'allow' if tools & {'Edit', 'Write'} else 'deny'}")
    lines.append(f"  glob: {'allow' if 'Glob' in tools else 'deny'}")
    lines.append(f"  grep: {'allow' if 'Grep' in tools else 'deny'}")
    lines.append(f"  list: {'allow' if 'LS' in tools else 'deny'}")
    if "Bash" in tools:
        lines.append("  bash:")
        lines.append('    "*": deny')
        lines.append('    "git log*": allow')
        lines.append('    "git diff*": allow')
        lines.append('    "git status": allow')
    else:
        lines.append('  bash:')
        lines.append('    "*": deny')
    lines.append("---\n")

    return "\n".join(lines) + body


def sync_agents(agents_dir: Path, target: str, dry_run: bool = False) -> None:
    """Fan agents/ out to a platform agent directory.

    claude / antigravity → copied verbatim (shared flat `tools` format).
    opencode             → frontmatter converted to a permission map.
    plugin               → no-op (agents/ is the authoring source).
    """
    if target == "plugin":
        print("  (plugin is the authoring source for agents — nothing to sync)")
        return

    agent_files = sorted(AGENTS_DIR.glob("*.md"))
    if not agent_files:
        print(f"No agent files found in {AGENTS_DIR}")
        sys.exit(1)

    for agent_path in agent_files:
        name = agent_path.stem
        text = agent_path.read_text()
        fields, body = parse_frontmatter(text)

        if not fields.get("description", "").strip():
            print(f"  SKIP  {name}  (no description in frontmatter)")
            continue

        if target == "opencode":
            new_content = build_opencode_agent(fields, body)
        else:  # claude, antigravity — keep Claude Code format verbatim
            new_content = text

        out_path = agents_dir / f"{name}.md"
        if out_path.exists() and out_path.read_text() == new_content:
            print(f"  OK    {name}  (unchanged)")
            continue
        action = "UPDATE" if out_path.exists() else "ADD"
        print(f"  {action}  {name}")
        if not dry_run:
            agents_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_content)

    if dry_run:
        print("\n(dry run — no files written)")


def sync(skills_dir: Path, dry_run: bool = False, delete_removed: bool = False) -> None:
    command_files = sorted(COMMANDS_DIR.glob("*.md"))
    if not command_files:
        print(f"No command files found in {COMMANDS_DIR}")
        sys.exit(1)

    synced_names: set[str] = set()

    for cmd_path in command_files:
        name = cmd_path.stem
        synced_names.add(name)

        text = cmd_path.read_text()
        fields, body = parse_frontmatter(text)
        description = fields.get("description", "").strip()

        if not description:
            print(f"  SKIP  {name}  (no description in frontmatter)")
            continue

        skill_dir = skills_dir / name
        skill_path = skill_dir / "SKILL.md"
        # Append the marker so that delete_removed works properly
        new_content = build_skill_frontmatter(name, description) + body + "\n\n# synced-from: issuesdb-plugin\n"

        if skill_path.exists():
            existing = skill_path.read_text()
            if existing == new_content:
                print(f"  OK    {name}  (unchanged)")
                continue
            action = "UPDATE"
        else:
            action = "ADD"

        print(f"  {action}  {name}")
        if not dry_run:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(new_content)

    if delete_removed:
        if skills_dir.exists():
            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                # Only remove dirs that were managed by this plugin
                # (i.e. their name matches a command that no longer exists)
                # We identify managed skills by checking if a corresponding
                # command file ever existed — safest heuristic: skip any skill
                # that was NOT produced from our commands/ dir this run.
                # To avoid deleting user-created skills, only delete if the
                # skill name was previously synced by this plugin (we track this
                # via a marker comment in SKILL.md).
                skill_path = skill_dir / "SKILL.md"
                if not skill_path.exists():
                    continue
                if skill_dir.name in synced_names:
                    continue
                if "# synced-from: issuesdb-plugin" not in skill_path.read_text():
                    continue
                print(f"  REMOVE  {skill_dir.name}")
                if not dry_run:
                    shutil.rmtree(skill_dir)

    if dry_run:
        print("\n(dry run — no files written)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    parser.add_argument("--delete-removed", action="store_true",
                        help="Remove skills whose command file no longer exists (only if marker present)")
    parser.add_argument("--target", choices=["plugin", "opencode", "claude", "antigravity"], default="plugin",
                        help="Target to sync to (choices: plugin, opencode, claude, antigravity; default: plugin)")
    parser.add_argument("--source", choices=["commands", "agents"], default="commands",
                        help="What to sync: commands -> skills, or agents -> platform agent dirs (default: commands)")
    args = parser.parse_args()

    if args.source == "agents":
        agents_dirs = {
            "plugin": PLUGIN_AGENTS_DIR,
            "opencode": OPENCODE_AGENTS_DIR,
            "antigravity": ANTIGRAVITY_AGENTS_DIR,
            "claude": DEFAULT_AGENTS_DIR,
        }
        agents_dir = agents_dirs[args.target]
        print(f"Source: {AGENTS_DIR}")
        print(f"Target: {agents_dir}\n")
        sync_agents(agents_dir, args.target, dry_run=args.dry_run)
        return

    if args.target == "plugin":
        skills_dir = PLUGIN_SKILLS_DIR
    elif args.target == "opencode":
        skills_dir = OPENCODE_SKILLS_DIR
    elif args.target == "antigravity":
        skills_dir = ANTIGRAVITY_SKILLS_DIR
    else:
        skills_dir = DEFAULT_SKILLS_DIR

    print(f"Source: {COMMANDS_DIR}")
    print(f"Target: {skills_dir}\n")
    sync(skills_dir, dry_run=args.dry_run, delete_removed=args.delete_removed)


if __name__ == "__main__":
    main()
