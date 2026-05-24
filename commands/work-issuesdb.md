---
description: Pull next ready issue from issuesdb, plan, implement TDD, test, open a PR, and report structured result (does NOT merge)
argument-hint: [optional issue id, otherwise picks highest-priority open issue]
---

# Work an issuesdb issue end-to-end

Pick up an open issue from issuesdb and drive it to a reviewable PR.

## Inputs

- `$ARGUMENTS` — optional: a specific issuesdb issue id. If empty, auto-select.

## Impact Tiers

Classify the issue before starting. This gates how much rigor to apply in each step.

| Signal | Tier 1 — Low | Tier 2 — Medium | Tier 3 — High |
|--------|-------------|-----------------|---------------|
| **What** | Docs, typos, copy/cosmetic, simple config | Bug fixes, new features in non-critical paths | Auth, security, data integrity, API contracts, schema changes, perf-critical paths |
| **Triage** | Quick self-check only | Full `issue-triage` subagent | Full `issue-triage` subagent |
| **Plan** | Inline comment only | `superpowers:writing-plans` | `superpowers:brainstorming` + `superpowers:writing-plans` |
| **Verify** | Run tests for affected files only | Full suite + lints + types | Full suite + lints + types + manually describe edge cases |
| **Security review** | Skip | Self-review: scan diff for injection, exposure, or broken access | Full `superpowers:code-reviewer` subagent security scan |

**When in doubt, go one tier higher.** If the issue touches auth, user data, payments, or external APIs anywhere in its call graph, use Tier 3 regardless of how small the change looks.

## Steps

### 1. Select the issue
- If `$ARGUMENTS` is non-empty: `mcp__issuesdb__get_issue` with that id.
- Otherwise: `mcp__issuesdb__list_projects` then `mcp__issuesdb__list_issues` (status=ready). Pick the highest-priority issue that is **not** blocked, **not** already in-progress, and has a clear enough description to act on. (`status=ready` means it has been groomed — ungroomed issues have `status=open` and should be run through `/groom-issue` first.)
- If nothing is actionable, STOP and report: "No actionable issues — top candidates: …" with a one-line reason for each.

### 2. Classify impact
- Assign a tier (1/2/3) using the table above. State it explicitly: "**Tier N — reason**". This determines steps 3–7.

### 3. Triage / pre-flight
- **Tier 1:** Quick self-check — does the issue description have enough to act on? If yes, proceed.
- **Tier 2–3:** Invoke the **`issue-triage`** subagent with the issue body. It returns: scope assessment, ambiguities, codebase touchpoints, risk flags.
- If triage (any tier) flags the issue as ambiguous or under-specified, STOP and post the questions as a comment via `mcp__issuesdb__add_comment`. Do not start implementation.

### 4. Plan
- **Tier 1:** Write a brief inline plan (a few bullet points). Post as a comment.
- **Tier 2:** Invoke `superpowers:writing-plans`. Post the plan as a comment.
- **Tier 3:** Invoke `superpowers:brainstorming` first, then `superpowers:writing-plans`. Post the plan as a comment.
- Update issue status to in-progress: `mcp__issuesdb__update_issue`.

### 5. Isolate
- Use `superpowers:using-git-worktrees` to create a fresh worktree+branch named `issue-<id>-<slug>`.
- All subsequent edits happen in that worktree.

### 6. Implement
- Use `superpowers:test-driven-development` and `superpowers:executing-plans`.
- Tests first, then implementation. No skipping the red step.

### 7. Verify
- **Tier 1:** Run tests scoped to affected files/packages. Paste actual output.
- **Tier 2–3:** Use `superpowers:verification-before-completion`. Run the full test suite, lints, and type checks. Paste actual output.
- If anything fails: fix root cause, do not bypass with `--no-verify` / `.skip` / disabling tests.

### 8. Security review
- **Tier 1:** Skip.
- **Tier 2:** Self-review the diff: scan for injection vectors, exposed secrets, broken access checks. If anything looks off, bump to Tier 3 handling.
- **Tier 3:** Spawn a `superpowers:code-reviewer` subagent focused on security, scoped to the changes in the worktree. Ask it to identify critical vulnerabilities, non-critical security issues, and bugs. It must report findings back — do not invoke `security-review` as a top-level skill (that ends the session).
- For any **critical** findings (any tier): fix them before proceeding. Do not open the PR with known critical issues.
- For any **non-critical** findings and any **bugs** surfaced during review: log each as a separate issue via `mcp__issuesdb__create_issue`. Include the finding details, affected file/line, and a reference to the current issue id. Do not block the PR on these.

### 9. Open PR (do NOT merge)
- Use `commit-commands:commit-push-pr`.
- PR description must link the issuesdb issue id and summarize the plan + verification evidence.
- **`commit-commands:commit-push-pr` handles git/GitHub only — its scope ends when it returns the PR URL. The three issuesdb steps below are YOUR responsibility as the orchestrating agent. They are not delegated to that skill and will not happen automatically. Execute them immediately after the PR URL is in hand:**
  1. `mcp__issuesdb__update_issue` — set `status=in-review`.
  2. `mcp__issuesdb__add_comment` — post the PR URL as a comment, e.g. "PR opened: <url>".
  3. `mcp__issuesdb__update_issue` — append the PR URL to the issue `description`, e.g. add a line "PR: <url>" at the end.

### 10. Report structured result
- Do NOT merge — the orchestrator (or human) handles merge policy separately.
- Output a machine-parseable result block at the very end of your response:

```
## RESULT
- tier: <1|2|3>
- pr_url: <url or "none">
- tests_pass: <true|false>
- security_findings: <none|N non-critical|N critical>
- status: <done|blocked>
```

Do not include any other text after this block. The orchestrator consumes it to decide review depth and merge eligibility.

## Guardrails

- Never force-push. Never push to `main`/`master` directly.
- Never edit `.env`, lockfiles, or CI secrets without explicit confirmation in the issue.
- If any step fails twice in a row, STOP and post a comment explaining the blocker. Don't thrash.
- One issue per run. Don't bundle.
