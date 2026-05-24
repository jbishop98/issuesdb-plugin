---
description: Orchestrate the issuesdb pipeline — groom, develop, review, merge, cleanup (one item per phase per invocation)
argument-hint: [issue-id] (when provided, scopes grooming and development to a specific issue; otherwise picks the next actionable item across all phases)
---

# Orchestrate the issuesdb pipeline

Run one full pipeline cycle: pick the next actionable item in each phase and process it. Dispatch subagents for grooming + development. Handle review, merge, and cleanup directly (read-only: no code edits by the orchestrator itself).

## Scoping

Capture `$ARGUMENTS`. If non-empty, set `scoped_issue_id = $ARGUMENTS` and operate in scoped mode:
- Phase 1 grooms ONLY `scoped_issue_id` via `get_issue(id)`, not the next global open issue.
- Phase 2 develops ONLY the same issue, if Phase 1 set it to `status=ready`.
- If the scoped issue was groomed to `status=needs-input` or `status=closed`, Phase 2 is skipped.
- Phases 3-5 remain global (review, merge, and cleanup follow existing per-phase logic).
- When `$ARGUMENTS` is empty (cron mode), behavior is unchanged — global `list_issues` for each phase.

## Phase loop

Execute each phase in order. If a phase has no work, skip to the next. If any phase completes successfully, continue to the next phase (don't exit early). Exit when all phases are exhausted or a hard stop is hit.

All phase transitions MUST comment-trail to issuesdb via `mcp__issuesdb__add_comment`. Prefix comments with "Orchestrator:" so they are distinguishable from human comments.

---

### Phase 1 — GROOM

**If `scoped_issue_id` is set (scoped mode):**

1. `mcp__issuesdb__get_issue(id=scoped_issue_id)` — verify the issue exists.
2. If not found: `mcp__issuesdb__add_comment(issue_id=scoped_issue_id, body="Orchestrator: invalid issue ID — not found.")`, exit.
3. Dispatch a **general subagent** via the Task tool with this prompt:
   ```
   /groom-issue scoped_issue_id
   ```
4. Parse the subagent's output for the `## RESULT` block:
   - `status=ready` → continue to Phase 2 (carry `scoped_issue_id` as the develop target)
   - `status=needs-input` → `mcp__issuesdb__add_comment(issue_id=scoped_issue_id, body="Orchestrator: grooming paused — N questions need human input.")`, skip Phases 2-4, continue to Phase 5
   - `status=closed` → skip Phases 2-4, continue to Phase 5
   - `status=none` → exit (nothing to groom)
5. If the subagent fails or times out: `mcp__issuesdb__add_comment(issue_id=scoped_issue_id, body="Orchestrator: grooming subagent failed. Will retry on next cycle.")`, exit.

**Otherwise (global / cron mode):**

1. `mcp__issuesdb__list_issues(status="open", limit=1)`
2. If no results: skip to Phase 2.
3. If found with `id=X`: dispatch a **general subagent** via the Task tool with this prompt:
   ```
   /groom-issue X
   ```
4. Parse the subagent's output for the `## RESULT` block:
   - `status=ready` → continue to Phase 2
   - `status=needs-input` → `mcp__issuesdb__add_comment(issue_id=X, body="Orchestrator: grooming paused — N questions need human input.")`, continue to Phase 2
   - `status=closed` → continue to Phase 2
   - `status=none` → exit (nothing to groom)
5. If the subagent fails or times out: `mcp__issuesdb__add_comment(issue_id=X, body="Orchestrator: grooming subagent failed. Will retry on next cycle.")`, exit.

---

### Phase 2 — DEVELOP

**If `scoped_issue_id` is set (scoped mode):**

1. If Phase 1 did NOT produce `status=ready` for the scoped issue: skip Phases 3, 4, and 5 entirely, then exit.
2. Set `Y = scoped_issue_id` (the issue ID from Phase 1 result, already confirmed ready).
3. Dispatch a **general subagent** via the Task tool with this prompt:
   ```
   /work-issuesdb Y
   ```
4. Parse the subagent's output for the `## RESULT` block. Save these values for subsequent phases:
   - `tier` (1|2|3)
   - `pr_url` (URL or "none")
   - `tests_pass` (true|false)
   - `security_findings` (none|N non-critical|N critical)
   - `status` (done|blocked)
5. If `status=blocked` or `pr_url="none"`: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: development blocked — see subagent output.")`, exit.
6. If `status=done`: continue to Phase 3.

**Otherwise (global / cron mode):**

1. `mcp__issuesdb__list_issues(status="ready", limit=1)`
2. If no results: skip Phases 3, 4, and 5 entirely (nothing to develop/review/merge), then exit.
3. If found with `id=Y`: dispatch a **general subagent** via the Task tool with this prompt:
   ```
   /work-issuesdb Y
   ```
4. Parse the subagent's output for the `## RESULT` block. Save these values for subsequent phases:
   - `tier` (1|2|3)
   - `pr_url` (URL or "none")
   - `tests_pass` (true|false)
   - `security_findings` (none|N non-critical|N critical)
   - `status` (done|blocked)
5. If `status=blocked` or `pr_url="none"`: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: development blocked — see subagent output.")`, exit.
6. If `status=done`: continue to Phase 3.

---

### Phase 3 — REVIEW

Review is only applicable if the development phase produced a PR and the tier is 2 or 3. Tier 1 skips review entirely.

1. **If tier == 1:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: Tier 1 — skipping review, eligible for auto-merge.")`
   - Skip to Phase 4.

2. **If tier == 2 or tier == 3 and tests_pass is false:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: tests failed — review skipped. Fix before merge.")`
   - Skip to Phase 4 (merge will be blocked).

3. **If tier == 2 or tier == 3 and tests_pass is true:**
   - Fetch the PR diff: `gh pr diff <pr_url>`
   - Construct a self-contained review prompt that includes:
     - The issue title and description
     - The full PR diff
     - Instructions to find critical vulnerabilities, non-critical security issues, bugs, and code quality problems
     - Instruction to output findings in a structured format
   - Run the review via bash, using a **different LLM model** for independent signal:
     ```bash
     opencode run --agent plan -m opencode/claude-opus-4-7 "<review prompt>" 2>&1
     ```
   - **If `opencode` is not available** (command not found): skip review and comment "Orchestrator: review skipped — opencode CLI not available."
   - Parse the review output for findings:
     - **Critical** (blockers — must fix before merge): security vulnerabilities, data loss, auth bypass
     - **Non-critical** (advisory): style issues, minor improvements, suggestions
     - **Bugs** (logic errors, broken behavior)
   - Post all findings as a PR review via `gh pr review <pr_url> --comment --body "<findings>"`
   - For non-critical findings: log each as a new issue via `mcp__issuesdb__create_issue`
   - For bugs: log each as a new issue via `mcp__issuesdb__create_issue`
   - Continue to Phase 4.

---

### Phase 4 — MERGE

Apply auto-merge policy based on tier and the outcome of prior phases.

1. **Tier 1 + tests_pass == true:**
   - `gh pr merge <pr_url> --squash --auto`
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: auto-merged (Tier 1, tests passed).")`
   - Continue to Phase 5.

2. **Tier 2 + tests_pass == true + no critical review findings:**
   - `gh pr merge <pr_url> --squash --auto`
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: auto-merged (Tier 2, review passed).")`
   - Continue to Phase 5.

3. **Tier 2 + (tests_pass == false OR critical review findings):**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: merge blocked — tests failed or review flagged critical issues. PR: <pr_url>")`
   - Skip Phase 5 (nothing to clean if not merged), exit.

4. **Tier 3:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: Tier 3 — requires human merge approval. PR: <pr_url>")`
   - Skip Phase 5, exit.

5. If `gh pr merge` fails (e.g. CI not passing, branch conflicts):
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: auto-merge failed — gh pr merge returned error. Check CI status.")`
   - Exit.

---

### Phase 5 — CLEANUP

Detect and clean up one merged branch per invocation.

1. Find merged branches: `git branch --merged origin/main | grep -E 'issue-\d+' | head -1`
2. If no merged branches: exit.
3. Extract the branch name. Parse the issue id from the name pattern `issue-<id>-*`.
4. Remove the worktree (if it exists):
   ```bash
   git worktree remove <path> --force 2>/dev/null || true
   ```
5. Delete the branch:
   ```bash
   git branch -D <branch_name>
   ```
6. Close the issue:
   - `mcp__issuesdb__update_issue(<id>, status="closed")`
   - `mcp__issuesdb__add_comment(issue_id=<id>, body="Orchestrator: cleanup complete — branch deleted, issue closed.")`
7. Exit.

## Guardrails

- **Never force-push. Never push to main/master directly.**
- **Never merge Tier 3 issues** — always require human approval.
- **Never skip the review phase for Tier 2** — review gating is mandatory for auto-merge eligibility.
- **All external subagents for grooming and development use the Task tool** (general subagent type).
- **The review phase uses `opencode run` via bash**, NOT the Task tool. This ensures a different model and independent process for review.
- If any subagent or shell command fails or times out, log the error as a comment and exit. The next orchestrator invocation will retry.
- If Phase 5 finds multiple merged branches, clean up only one per invocation (keeps the run bounded).
- The orchestrator itself is **read-only** — it never edits code, only dispatches subagents, runs bash commands, and updates issuesdb.
- One invocation, one cycle. Do not loop internally — cron handles repetition.
