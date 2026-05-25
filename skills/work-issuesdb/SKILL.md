---
name: work-issuesdb
description: >
  Pull next ready issue from issuesdb, plan, implement TDD, test, open a PR, and report structured result (does NOT merge)
---

# Work an issuesdb issue end-to-end

Pick up an open issue from issuesdb and drive it to a reviewable PR. Update the session summary to "Work <issue #> < issue title>"

## Inputs

- `$ARGUMENTS` — optional: one or more issuesdb issue ids, optionally followed by `--tier N` (1/2/3).
  - `issue_id` — work this specific issue.
  - `issue_id --tier N` — work this issue with tier pre-classified by the orchestrator; skip self-triage.
  - `id1 id2 id3 --tier 1` — work a bundle of Tier 1 issues in one pass; only the orchestrator may pass multiple IDs.
  - empty — auto-select the next ready issue and self-classify.

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
- Parse `$ARGUMENTS`: extract one or more `issue_id`s and optional `--tier N`. If `--tier N` is present, set `provided_tier = N`; otherwise `provided_tier = null`.
- Set `issue_ids = [all extracted ids]`, `primary_id = issue_ids[0]`.
- If `issue_ids` is non-empty: `mcp__issuesdb__get_issue` for each id in `issue_ids`.
- Otherwise: `mcp__issuesdb__list_projects` then `mcp__issuesdb__list_issues` (status=ready). Pick the highest-priority issue that is **not** blocked, **not** already in-progress, and has a clear enough description to act on. Set `issue_ids = [picked_id]`, `primary_id = picked_id`. (`status=ready` means it has been groomed — ungroomed issues have `status=open` and should be run through `/groom-issue` first.)
- **Bundle safety check**: if `len(issue_ids) > 1`, verify all issues look like Tier 1 (docs, typos, copy, simple config). If any issue shows Tier 2+ signals, drop it from the bundle and log a warning comment on that issue: "Orchestrator: dropped from bundle — issue appears to be Tier 2+, will be worked separately."
- If nothing is actionable, STOP and report: "No actionable issues — top candidates: …" with a one-line reason for each.

### 2. Classify impact
- **If `provided_tier` is set:** use it directly. State: "**Tier N — pre-classified by orchestrator**". Skip to Step 3.
- **Otherwise:** assign a tier (1/2/3) using the table above. State it explicitly: "**Tier N — reason**". This determines steps 3–7.

### 3. Triage / pre-flight
- **If `provided_tier` is set:** skip this step entirely — the orchestrator has already run `issue-triage` and resolved ambiguities.
- **Tier 1:** Quick self-check — does the issue description have enough to act on? If yes, proceed.
- **Tier 2–3:** Invoke the **`issue-triage`** subagent with the issue body. It returns: scope assessment, ambiguities, codebase touchpoints, risk flags.
- If triage (any tier) flags the issue as ambiguous or under-specified, STOP and post the questions as a comment via `mcp__issuesdb__add_comment`. Do not start implementation.

### 4. Plan
- **Tier 1:** Write a brief inline plan (a few bullet points). Post as a comment.
- **Tier 2:** Invoke `superpowers:writing-plans`. Post the plan as a comment.
- **Tier 3:** Invoke `superpowers:brainstorming` first, then `superpowers:writing-plans`. Post the plan as a comment.
- Update all issues in `issue_ids` to in-progress: `mcp__issuesdb__update_issue` for each id.

### 5. Isolate
- **Single issue:** Use `superpowers:using-git-worktrees` to create a fresh worktree+branch named `issue-<id>-<slug>`.
- **Bundle (`len(issue_ids) > 1`):** Use `superpowers:using-git-worktrees` to create a fresh worktree+branch named `issue-<primary_id>-bundle`.
- All subsequent edits happen in that worktree.

### 6. Implement
- Use `superpowers:test-driven-development` and `superpowers:executing-plans`.
- Tests first, then implementation. No skipping the red step.
- **Bundle:** work through each issue in `issue_ids` sequentially in the same worktree. If any single issue in the bundle is blocked, skip it, note it in the RESULT, and continue with the remaining issues. Complete as many as possible.

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
- PR description must link all issuesdb issue ids in `issue_ids` and summarize the plan + verification evidence.
- **`commit-commands:commit-push-pr` handles git/GitHub only — its scope ends when it returns the PR URL. The issuesdb steps below are YOUR responsibility. They are not delegated to that skill and will not happen automatically. Execute them immediately after the PR URL is in hand.**
- For **each** id in `issue_ids`:
  1. `mcp__issuesdb__update_issue` — set `status=in-review`.
  2. `mcp__issuesdb__add_comment` — post the PR URL as a comment, e.g. "PR opened: <url>".
  3. `mcp__issuesdb__update_issue` — append the PR URL to the issue `description`, e.g. add a line "PR: <url>" at the end.

### 10. Report structured result
- Do NOT merge — the orchestrator (or human) handles merge policy separately.
- Output a machine-parseable result block at the very end of your response:

```
## RESULT
- tier: <1|2|3>
- issue_ids: <id> or <id1,id2,id3>
- pr_url: <url or "none">
- tests_pass: <true|false>
- security_findings: <none|N non-critical|N critical>
- status: <done|blocked|partial>
```

`issue_ids`: comma-separated list of all issue IDs resolved in this run (single-issue runs emit one ID).
`status=partial`: some bundled issues completed but at least one was skipped due to a blocker — PR was still opened for the completed ones.

Do not include any other text after this block. The orchestrator consumes it to decide review depth and merge eligibility.

## Guardrails

- Never force-push. Never push to `main`/`master` directly.
- Never edit `.env`, lockfiles, or CI secrets without explicit confirmation in the issue.
- If any step fails twice in a row, STOP and post a comment explaining the blocker. Don't thrash.
- Never self-select multiple issues. Only accept a bundle when the orchestrator passes multiple IDs with `--tier 1`. Tier 2/3: one issue per run, no exceptions.


# synced-from: issuesdb-plugin
