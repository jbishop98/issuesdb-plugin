---
description: Pull next open issue from issuesdb, plan, implement TDD, test, and open a PR (does NOT merge)
argument-hint: [optional issue id, otherwise picks highest-priority open issue]
---

# Work an issuesdb issue end-to-end

Pick up an open issue from issuesdb and drive it to a reviewable PR.

## Inputs

- `$ARGUMENTS` — optional: a specific issuesdb issue id. If empty, auto-select.

## Steps

### 1. Select the issue
- If `$ARGUMENTS` is non-empty: `mcp__issuesdb__get_issue` with that id.
- Otherwise: `mcp__issuesdb__list_projects` then `mcp__issuesdb__list_issues` (status=ready). Pick the highest-priority issue that is **not** blocked, **not** already in-progress, and has a clear enough description to act on. (`status=ready` means it has been groomed — ungroomed issues have `status=open` and should be run through `/groom-issue` first.)
- If nothing is actionable, STOP and report: "No actionable issues — top candidates: …" with a one-line reason for each.

### 2. Triage / pre-flight
- Invoke the **`issue-triage`** subagent with the issue body. It returns: scope assessment, ambiguities, codebase touchpoints, risk flags.
- If triage flags the issue as ambiguous or under-specified, STOP and post the questions as a comment via `mcp__issuesdb__add_comment`. Do not start implementation.

### 3. Plan
- Invoke `superpowers:writing-plans` (or `superpowers:brainstorming` first if the design space is open).
- Post the final plan back to the issue with `mcp__issuesdb__add_comment`.
- Update issue status to in-progress: `mcp__issuesdb__update_issue`.

### 4. Isolate
- Use `superpowers:using-git-worktrees` to create a fresh worktree+branch named `issue-<id>-<slug>`.
- All subsequent edits happen in that worktree.

### 5. Implement
- Use `superpowers:test-driven-development` and `superpowers:executing-plans`.
- Tests first, then implementation. No skipping the red step.

### 6. Verify
- Use `superpowers:verification-before-completion`. Run the full test suite, lints, and type checks. Paste actual output.
- If anything fails: fix root cause, do not bypass with `--no-verify` / `.skip` / disabling tests.

### 7. Security review
- Spawn a `superpowers:code-reviewer` subagent focused on security, scoped to the changes in the worktree. Ask it to identify critical vulnerabilities, non-critical security issues, and bugs. It must report findings back — do not invoke `security-review` as a top-level skill (that ends the session).
- For any **critical** findings: fix them before proceeding. Do not open the PR with known critical issues.
- For any **non-critical** findings and any **bugs** surfaced during the review: log each as a separate issue via `mcp__issuesdb__create_issue`. Include the finding details, affected file/line, and a reference to the current issue id in the description. Do not block the PR on these.

### 8. Open PR (do NOT merge)
- Use `commit-commands:commit-push-pr`.
- PR description must link the issuesdb issue id and summarize the plan + verification evidence.
- Once you have the PR URL, do ALL of the following — do not skip any:
  1. `mcp__issuesdb__update_issue` — set `status=in-review`.
  2. `mcp__issuesdb__add_comment` — post the PR URL as a comment, e.g. "PR opened: <url>".
  3. `mcp__issuesdb__update_issue` — append the PR URL to the issue `description`, e.g. add a line "PR: <url>" at the end.

### 9. Stop
- **Do not merge.** Merging requires explicit human approval. Report the PR URL and exit.

## Guardrails

- Never force-push. Never push to `main`/`master` directly.
- Never edit `.env`, lockfiles, or CI secrets without explicit confirmation in the issue.
- If any step fails twice in a row, STOP and post a comment explaining the blocker. Don't thrash.
- One issue per run. Don't bundle.
