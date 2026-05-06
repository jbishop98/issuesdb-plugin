# issuesdb-plugin

Claude Code plugin for grooming and working [issuesdb](https://github.com/anthropics/claude-code) issues end-to-end.

## Skills

### `/groom-issue [issue-id]`
Takes a raw `status=open` issue and turns it into something an implementer can act on — clarifies scope, acceptance criteria, and marks it `status=ready` when done.

### `/work-issuesdb [issue-id]`
Picks up a `status=ready` issue and drives it to a reviewable PR: triage → plan → worktree → TDD implementation → security review → PR.

## Dependencies

These skills rely on the following plugins being installed:

- **superpowers** — provides `superpowers:writing-plans`, `superpowers:brainstorming`, `superpowers:test-driven-development`, `superpowers:executing-plans`, `superpowers:verification-before-completion`, `superpowers:using-git-worktrees`
- **commit-commands** — provides `commit-commands:commit-push-pr`

And the **issuesdb MCP server** must be configured in your Claude Code MCP settings.

## Installation

```bash
claude plugin install github:jbishop98/issuesdb-plugin
```
