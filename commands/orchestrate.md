---
description: Orchestrate the issuesdb pipeline — groom, triage, develop, review, merge, cleanup (one item per phase per invocation)
argument-hint: [issue-id ...] (one or more IDs scopes grooming and development; multiple IDs in the same project are bundled; otherwise picks the next actionable item across all phases)
argument-hint: none (processes the next actionable item across all phases; cron-compatible)
---

# Orchestrate the issuesdb pipeline

Run one full pipeline cycle: pick the next actionable item in each phase and process it. Dispatch subagents for grooming + development. Triage runs directly in the orchestrator for visibility. Handle review, merge, and cleanup directly (read-only: no code edits by the orchestrator itself).

## Scoping

Capture `$ARGUMENTS` and split by whitespace to get `scoped_ids` list.

**If `scoped_ids` is non-empty, operate in scoped mode:**
- If `scoped_ids` contains a single ID: set `bundle_ids = [scoped_ids[0]]`.
- If `scoped_ids` contains multiple IDs: fetch each via `get_issue(id)` to confirm they exist and share the same `project` field. If projects differ, comment on the primary ID ("Orchestrator: bundling requires all IDs to share the same project — aborting.") and exit. Set `bundle_ids = scoped_ids`.
- Phase 1 grooms each issue in `bundle_ids` (skipping any already at Ready or In-Progress).
- Phase 2 triages using `bundle_ids[0]` as the representative — tier classification applies to the whole bundle.
- Phase 3 develops all issues in `bundle_ids` together.
- If any issue is groomed to `status=needs-input` or `status=closed`, it is dropped from `bundle_ids`; if `bundle_ids` becomes empty, Phases 2-5 are skipped.
- Phases 4-6 remain global (review, merge, and cleanup follow existing per-phase logic).

**If `$ARGUMENTS` is empty (cron mode):** behavior is unchanged — global `list_issues` for each phase.

## Phase loop

Execute each phase in order. If a phase has no work, skip to the next. If any phase completes successfully, continue to the next phase (don't exit early). Exit when all phases are exhausted or a hard stop is hit.

Comment-trail the **decisions** that matter for unattended visibility — tier classification, halt / needs-input, development blocked, and merge outcome. Skip purely procedural notes (e.g. "cleanup complete", "skipping review"). Prefix all comments with "Orchestrator:" so they're distinguishable from human comments.

---

### Phase 1 — GROOM

**If in scoped mode (`bundle_ids` set):**

For each id in `bundle_ids` (process sequentially):
1. `mcp__issuesdb__get_issue(id=id)` — if state is Ready or In-Progress, it is already groomed; skip subagent dispatch and keep in `bundle_ids`.
2. If not found: `mcp__issuesdb__add_comment(issue_id=id, body="Orchestrator: invalid issue ID — not found.")`, remove from `bundle_ids`, continue.
3. If open and needs grooming, dispatch a **general subagent** via the Task tool:
   ```
   /groom-issue <id>
   ```
4. Parse the subagent's output for the `## RESULT` block:
   - `status=ready` → keep in `bundle_ids`
   - `status=needs-input` → `mcp__issuesdb__add_comment(issue_id=<id>, body="Orchestrator: grooming paused — N questions need human input.")`, remove from `bundle_ids`
   - `status=closed` → remove from `bundle_ids`
   - `status=none` → remove from `bundle_ids`
5. If the subagent fails or times out: `mcp__issuesdb__add_comment(issue_id=<id>, body="Orchestrator: grooming subagent failed. Will retry on next cycle.")`, remove from `bundle_ids`.

After processing all issues:
- If `bundle_ids` is empty: exit.
- If `len(bundle_ids) > 1`: `mcp__issuesdb__add_comment(issue_id=bundle_ids[0], body="Orchestrator: bundling <N> issues into single PR: #id1, #id2, ...")`
- Continue to Phase 2.

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

- **Scoped mode:** `Y = bundle_ids[0]` (primary issue, confirmed ready from Phase 1). If `bundle_ids` is empty after Phase 1, skip Phases 2-5 and go to Phase 6.
- **Global/cron mode:** `mcp__issuesdb__list_issues(status="ready", limit=5)`. If no results, skip to Phase 3.

**Classify impact tier** from the issue title and description:

| Signal   | Tier 1 — Low                              | Tier 2 — Medium                               | Tier 3 — High                                                                      |
| -------- | ----------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------- |
| **What** | Docs, typos, copy/cosmetic, simple config | Bug fixes, new features in non-critical paths | Auth, security, data integrity, API contracts, schema changes, perf-critical paths |

> Tier definitions are **canonical in the `triage-issue` skill** — keep this table in sync with it.

When in doubt, go one tier higher. If the issue touches auth, user data, payments, or external APIs anywhere in its call graph, use Tier 3. Post the classification immediately: `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: classified Tier N — <one-line reason>.")`

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

> The orchestrator invokes the `issue-triage` **agent** directly (not the `/triage-issue` skill) because it needs the full structured report — touchpoints and risk_flags — to forward into development, not just a tier verdict. `/triage-issue` is for standalone human-driven routing.

Dispatch with the **full issue content inline** (title, description, and comments — you already have this from the Phase 1 `get_issue` call) plus the repo cwd. Pass it as:

```
Issue #<Y> — <title>

<full description>

--- comments ---
<each comment body in order>
```

The agent will skip its own `get_issue` fetch when content is provided this way. Also tell the agent to **validate and extend** the `## Touchpoints` section grooming already wrote into the issue body, rather than rebuilding it from scratch. Parse the structured report for:
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

**If in scoped mode and Phase 2 did not clear the issue for development:** skip Phases 3–6.

Set issue status to in-progress. Dispatch `/work-issuesdb` with the tier pre-provided so the subagent skips its own triage. **A single issue is just a one-element bundle** — one dispatch rule covers all modes.

Always include the **full issue content inline** for each id in `bundle_ids` — you already have this from earlier fetches; passing it means the subagent skips its own `get_issue` calls:

```
Issue #<id> — <title>
<description>
--- comments ---
<comments>
```

**Tier 1** (no `triage_report`):
```
/work-issuesdb <space-separated bundle_ids> --tier 1
<inline issue content for each id>
```

**Tier 2 / Tier 3** — also forward the triage context so the subagent uses it as its starting map instead of re-scanning the codebase from scratch:
```
/work-issuesdb <space-separated bundle_ids> --tier <tier>
<inline issue content for each id>
Touchpoints from triage:
- <path> — <role>
- ...
Key risk flags from triage: <risk_flags summary>
```

Parse the subagent's output for the `## RESULT` block. Save these values for subsequent phases:
- `tier` (1|2|3)
- `issue_ids` (comma-separated; single-issue runs emit one ID — set `bundle_ids = issue_ids list`)
- `pr_url` (URL or "none")
- `tests_pass` (true|false)
- `security_findings` (none|N non-critical|N critical)
- `status` (done|blocked|partial)

If `status=blocked` or `pr_url="none"`:
- `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: development blocked — see subagent output.")`, exit.
If `status=done` or `status=partial`:
- For each id in `bundle_ids`: `mcp__issuesdb__update_issue(id=<id>, pull_request=<pr_url>)` to set the PR URL on the issue record.
- continue to Phase 4.

---

### Phase 4 — REVIEW

Review is only applicable if the development phase produced a PR and the tier is 2 or 3. Tier 1 skips review entirely.

> This opencode pass is the **authoritative independent security/code review** for Tier 2–3. `/work-issuesdb` deliberately does **not** spawn its own review subagent (it does only a cheap inline self-scan), so this phase is not redundant — it is the one heavyweight review, run on the real PR diff with a different model.

1. **If tier == 1:**
   - Skip to Phase 5 (Tier 1 is review-exempt; the merge comment records the outcome).

2. **If tier == 2 or tier == 3 and tests_pass is false:**
   - `mcp__issuesdb__add_comment(issue_id=Y, body="Orchestrator: tests failed — review skipped. Fix before merge.")`
   - Skip to Phase 5 (merge will be blocked).

3. **If tier == 2 or tier == 3 and tests_pass is true:**
   - Run the review via bash, using a **different LLM model** for independent signal (opencode uses `gh` CLI to fetch the PR):
     ```bash
     opencode run --agent plan -m opencode-go/deepseek-v4-pro "/review <pr_url>" 2>&1
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
   - For each id being closed: `mcp__issuesdb__update_issue(<id>, status="closed")`. (No separate "cleanup complete" comment — the status change is the trail.)
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
