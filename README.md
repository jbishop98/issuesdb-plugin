# issuesdb-plugin

A unified plugin for **Claude Code** and **Google Antigravity** to groom and work [issuesdb](https://github.com/jbishop98/issuesdb) issues end-to-end.

This plugin is structured to comply with both the Claude Code and Google Antigravity plugin definitions, packaging MCP servers, skills, and configuration into a single directory.

## Skills

### `/groom-issue [issue-id]`
Takes a raw `status=open` issue and turns it into something an implementer can act on — clarifies scope, acceptance criteria, and marks it `status=ready` when done.

### `/work-issuesdb [issue-id]`
Picks up a `status=ready` issue and drives it to a reviewable PR: triage → plan → worktree → TDD implementation → security review → PR.

## Directory Structure

- `plugin.json` — Manifest file for Google Antigravity.
- `.claude-plugin/plugin.json` — Manifest file for Claude Code.
- `mcp_config.json` — MCP configurations for Google Antigravity.
- `.mcp.json` — MCP configurations for Claude Code.
- `skills/` — The generated & committed skills directories containing `SKILL.md` for both agents.
- `commands/` — Command markdown files, which are symlinked to by `opencode`.
- `agents/` — Subagent definitions in Claude Code format (the authoring source). Fanned out to each platform by the sync script.
- `scripts/sync_skills.py` — Helper script to sync/generate skills and agents.

## Syncing & Maintenance Workflow

The repo has two authoring sources, each selected with `--source`:

- `commands/` (default) — single source of truth for skills; compiled into `SKILL.md` files.
- `agents/` — single source of truth for subagents, authored in Claude Code format (flat `tools` allowlist, `model` alias). The script fans them out, converting frontmatter per platform: Claude Code and Antigravity get the file verbatim; OpenCode gets a converted `permission` map and a provider-qualified `model` id.

When you modify any file in `commands/` or `agents/`, run the sync script before committing:

```bash
# Compile and generate/update the skills/ directory in the plugin repo (default):
python scripts/sync_skills.py

# Sync skills to opencode's configuration directory:
python scripts/sync_skills.py --target opencode

# Sync skills to global/legacy directories (optional):
python scripts/sync_skills.py --target claude
python scripts/sync_skills.py --target antigravity

# Sync agents/ out to each platform's agent directory:
python scripts/sync_skills.py --source agents --target claude        # -> ~/.claude/agents/
python scripts/sync_skills.py --source agents --target opencode       # -> ~/.config/opencode/agent/ (converted)
python scripts/sync_skills.py --source agents --target antigravity    # -> ~/.gemini/antigravity/agents/
```

## Dependencies

These skills rely on the following plugins being installed:

- **superpowers** — provides `superpowers:writing-plans`, `superpowers:brainstorming`, `superpowers:test-driven-development`, `superpowers:executing-plans`, `superpowers:verification-before-completion`, `superpowers:using-git-worktrees`
- **commit-commands** — provides `commit-commands:commit-push-pr`

## Installation

### Claude Code

```bash
claude plugin install github:jbishop98/issuesdb-plugin
```

### Google Antigravity

Add the plugin folder to your project-level `.agents/plugins/` (or `_agents/plugins/`) or link/copy it globally to `~/.gemini/config/plugins/`.

