---
description: Orchestrate the issuesdb pipeline — groom, triage, develop, review, merge, cleanup (one item per phase per invocation)
argument-hint: [issue-id] (when provided, scopes grooming and development to a specific issue; otherwise picks the next actionable item across all phases)
argument-hint: none (processes the next actionable item across all phases; cron-compatible)
---

# Orchestrate the issuesdb pipeline

Run one full pipeline cycle: pick the next actionable item in each phase and process it. Dispatch subagents for grooming + development. Triage runs directly in the orchestrator for visibility. Handle review, merge, and cleanup directly (read-only: no code edits by the orchestrator itself).

## Scoping

Capture `$ARGUMENTS`. If non-empty, set `scoped_issue_id = $ARGUMENTS` and operate in scoped mode:
- Phase 1 grooms ONLY `scoped_issue_id` via `get_issue(id)`, not the next global open issue.
- Phase 2 triages ONLY the same issue.
- Phase 3 develops ONLY the same issue, if Phase 2 cleared it for development.
- If the scoped issue was groomed to `status=needs-input` or `status=closed`, Phases 2-4 are skipped.
- Phases 4-6 remain global (review, merge, and cleanup follow existing per-phase logic).
- When `$ARGUMENTS` is empty (cron mode), behavior is unchanged — global `list_issues` for each phase.

## Phase loop

Execute each phase in order. If a phase has no work, skip to the next. If any phase completes successfully, continue to the next phase (don't exit early). Exit when all phases are exhausted or a hard stop is hit.

All phase transitions MUST comment-trail to issuesdb via `mcp__issuesdb__add_comment`. Prefix comments with "Orchestrator:" so they are distinguishable from human comments.

---

### Phase 1 — GROOM

**If `scoped_issue_id` is set (scoped mode):**

1. `mcp__issuesdb__get_issue(id=scoped_issue_id)` — verify the issue exists, and is in an open state (if state is Ready or In-Progress, it's already groomed therefore this phase can be skipped)
2. If not found: `mcp__issuesdb__add_comment(issue_id=scoped_issue_id, body="Orchestrator: invalid issue ID — not found.")`, exit.
3. Dispatch a **general subagent** via the Task tool with this prompt:
   ```
   /groom-issue scoped_issue_id
   ```
4. Parse the subagent's output for the `## RESULT` block:
   - `status=ready` → continue to Phase 2 (carry `scoped_issue_id` as the triage/develop target)
   - `status=needs-input` → `mcp__issuesdb__add_comment(issue_id=scoped_issue_id, body="Orchestrator: grooming paused — N questions need human input.")`, skip Phases 2-5, continue to Phase 6
   - `status=closed` → skip Phases 2-5, continue to Phase 6
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

### Phase 2 — TRIAGE

**Find the issue to triage:**

- **Scoped mode:** `Y = scoped_issue_id` (already confirmed ready from Phase 1). If Phase 1 did not produce `status=ready`, skip Phases 2-5 entirely and go to Phase 6.
- **Global/cron mode:** `mcp__issuesdb__list_issues(status="ready", limit=5)`. If no results, skip to Phase 3.

**Classify impact tier** from the issue title and description:

| Signal | Tier 1 — Low | Tier 2 — Medium | Tier 3 — High |
|--------|-------------|-----------------|---------------|
| **What** | Docs, typos, copy/cosmetic, simple config | Bug fixes, new features in non-critical paths | Auth, security, data integrity, API contracts, schema changes, perf-critical paths |

When in doubt, go one tier higher. If the issue touches auth, user data, or external APIs anywhere in its call graph, use Tier 3. Post the classification immediately: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: classified Tier N — <one-line reason>.")`

**Ingest the md context files from the relevant project** so you can issue special instructions to the development subagent where applicable.

**Tier 1 — skip triage subagent (global/cron mode: also discover bundle peers):**

Set `triage_report = null`.

**In global/cron mode only**, check for additional Tier 1 peers in the same project before dispatching development:
1. Note the `project` field from issue Y's object (call `mcp__issuesdb__get_issue(id=Y)` if needed to retrieve it).
2. `mcp__issuesdb__list_issues(status="ready", project=Y.project, limit=5)` — fetch other ready issues in the same project.
3. Filter out Y itself. Scan remaining issues' titles/descriptions — keep only those with clear Tier 1 signals (docs, typos, copy, simple config). Exclude any showing Tier 2+ signals (bug fixes, feature work, auth, schema, perf).
4. Cap at 3 additional issues (total bundle ≤ 4).
5. Set `bundle_ids = [Y, id2, id3, ...]`. If no qualifying peers: `bundle_ids = [Y]`.
6. If `len(bundle_ids) > 1`: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: bundling <N> Tier 1 issues from project <project> into single PR: #Y, #id2, ...")`

Continue to Phase 3.

**Tier 2–3 — invoke the `issue-triage` subagent:**

Dispatch with the issue body and the repo cwd. Parse the structured report for:
- `ambiguities` — blocking questions that must be answered before code can be written
- `touchpoints` — files/modules most likely to change
- `risk_flags` — data migrations, auth surface, breaking changes, shared infra
- `recommendation` — Proceed / Proceed with caution / Halt

**If recommendation == Halt:**
- Post the blocking questions as a comment: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: triage flagged blocking ambiguities — needs human input before development.\n\n<questions>")`
- `mcp__issuesdb__update_issue(id=Y, status="needs-input")`
- Skip Phases 3–5, continue to Phase 6.

**If recommendation == Proceed with caution:**
- Post risk summary: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: triage complete — proceeding with caution.\n\nRisk flags:\n<risk_flags>")`
- Ensure `tier >= 2` (never downgrade based on caution signal).
- Save `triage_report`. Continue to Phase 3.

**If recommendation == Proceed:**
- Save `triage_report`. Continue to Phase 3.

---

### Phase 3 — DEVELOP

Receives `Y` (issue id), `tier` (1/2/3), and `triage_report` from Phase 2.

**If `scoped_issue_id` is set and Phase 2 did not clear the issue for development:** skip Phases 3–6.

Dispatch `/work-issuesdb` with tier pre-provided so the subagent skips its own triage:

**Tier 1 (scoped mode — always single issue):**
```
/work-issuesdb Y --tier 1
```

**Tier 1 (global/cron mode — single issue, no qualifying peers):**
```
/work-issuesdb Y --tier 1
```

**Tier 1 (global/cron mode — bundle, `len(bundle_ids) > 1`):**
```
/work-issuesdb id1 id2 id3 --tier 1
```
Pass all IDs in `bundle_ids` as space-separated arguments.

**Tier 2:**
```
/work-issuesdb Y --tier 2
```

**Tier 3** — also forward the triage context to orient the subagent:
```
/work-issuesdb Y --tier 3
Key risk flags from triage: <risk_flags summary>
Touchpoints: <touchpoints list>
```

Parse the subagent's output for the `## RESULT` block. Save these values for subsequent phases:
- `tier` (1|2|3)
- `issue_ids` (comma-separated; single-issue runs emit one ID — set `bundle_ids = issue_ids list`)
- `pr_url` (URL or "none")
- `tests_pass` (true|false)
- `security_findings` (none|N non-critical|N critical)
- `status` (done|blocked|partial)

If `status=blocked` or `pr_url="none"`: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: development blocked — see subagent output.")`, exit.
If `status=done` or `status=partial`: continue to Phase 4.

---

### Phase 4 — REVIEW

Review is only applicable if the development phase produced a PR and the tier is 2 or 3. Tier 1 skips review entirely.

1. **If tier == 1:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: Tier 1 — skipping review, eligible for auto-merge.")`
   - Skip to Phase 5.

2. **If tier == 2 or tier == 3 and tests_pass is false:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: tests failed — review skipped. Fix before merge.")`
   - Skip to Phase 5 (merge will be blocked).

3. **If tier == 2 or tier == 3 and tests_pass is true:**
   - Fetch the PR diff: `gh pr diff <pr_url>`
   - Construct a self-contained review prompt that includes:
     - The issue title and description
     - The full PR diff
     - Instructions to find critical vulnerabilities, non-critical security issues, bugs, and code quality problems
     - Instruction to output findings in a structured format
   - Run the review via bash, using a **different LLM model** for independent signal:
     ```bash
     opencode run --agent plan -m opencode/deepseek-v4-flash-free "<review prompt>" 2>&1
     ```
   - **If `opencode` is not available** (command not found): skip review and comment "Orchestrator: review skipped — opencode CLI not available."
   - Parse the review output for findings:
     - **Critical** (blockers — must fix before merge): security vulnerabilities, data loss, auth bypass
     - **Non-critical** (advisory): style issues, minor improvements, suggestions
     - **Bugs** (logic errors, broken behavior)
   - Post all findings as a PR review via `gh pr review <pr_url> --comment --body "<findings>"`
   - For non-critical findings: log each as a new issue via `mcp__issuesdb__create_issue`
   - For low priority bugs: log each as a new issue via `mcp__issuesdb__create_issue`
   - For all other bugs/issues: fix immediately
   - Continue to Phase 5.

---

### Phase 5 — MERGE

Apply auto-merge policy based on tier and the outcome of prior phases.

1. **Tier 1 + tests_pass == true:**
   - `gh pr merge <pr_url> --squash --auto`
   - For each id in `bundle_ids`: `mcp__issuesdb__add_comment(issue_id=<id>, body="Orchestrator: auto-merged (Tier 1, tests passed).")`
   - Continue to Phase 6.

2. **Tier 2 + tests_pass == true + no critical review findings:**
   - `gh pr merge <pr_url> --squash --auto`
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: auto-merged (Tier 2, review passed).")`
   - Continue to Phase 6.

3. **Tier 2 + (tests_pass == false OR critical review findings):**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: merge blocked — tests failed or review flagged critical issues. PR: <pr_url>")`
   - Skip Phase 6 (nothing to clean if not merged), exit.

4. **Tier 3:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: Tier 3 — requires human merge approval. PR: <pr_url>")`
   - Skip Phase 6, exit.

5. If `gh pr merge` fails (e.g. CI not passing, branch conflicts):
   - Attempt to fix conflicts if they are obvious and aren't conflicting with what are clearly other new features
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: auto-merge failed — gh pr merge returned error. Check CI status.")`
   - Exit.

---

### Phase 6 — CLEANUP

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
6. Close issues:
   - If `bundle_ids` is available from this invocation's Phase 3 RESULT: close each id in `bundle_ids`.
   - Otherwise (cross-invocation cleanup): close only the primary `<id>` parsed from the branch name.
   - For each id being closed: `mcp__issuesdb__update_issue(<id>, status="closed")` and `mcp__issuesdb__add_comment(issue_id=<id>, body="Orchestrator: cleanup complete — branch deleted, issue closed.")`
7. Exit.

## Guardrails

- **Never force-push. Never push to main/master directly.**
- **Never merge Tier 3 issues** — always require human approval.
- **Never skip the review phase for Tier 2** — review gating is mandatory for auto-merge eligibility.
- **Triage runs in the orchestrator, not inside the development subagent.** This is intentional — the orchestrator must see ambiguities, risk flags, and tier before committing to development.
- **All external subagents for grooming and development use the Task tool** (general subagent type).
- **The review phase uses `opencode run` via bash**, NOT the Task tool. This ensures a different model and independent process for review.
- If any subagent or shell command fails or times out, log the error as a comment and exit. The next orchestrator invocation will retry.
- If Phase 6 finds multiple merged branches, clean up only one per invocation (keeps the run bounded).
- The orchestrator itself is **read-only** — it never edits code, only dispatches subagents, runs bash commands, and updates issuesdb.
- One invocation, one cycle. Do not loop internally — cron handles repetition.
