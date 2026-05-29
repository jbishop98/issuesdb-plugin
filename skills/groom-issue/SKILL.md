---
name: groom-issue
description: >
  Groom an issue from the issuesdb tracker (any project) — clarify scope, acceptance criteria, and readiness for implementation
---

# Groom an issue tracked in issuesdb

Take a raw issue and turn it into something an implementer (human or agent) can act on without guessing.

> **issuesdb is the tracker, not the target codebase.** It stores issues for many projects (rentaway, SRApp, SROps, finops, stylerotate-wishlist, and the issuesdb app itself). The issue you're grooming belongs to *one* of those projects — identified by its `project` field. All codebase work happens in *that* project's repo, never in the issuesdb app repo (unless `project == "issuesdb"`).

**Groomed issues are marked with `status=ready`.** Ungroomed issues have `status=open`. This is the queue — grooming one removes it from the ungroomed list and makes it visible to `/work-issuesdb`.

## Inputs

- `$ARGUMENTS` — the issuesdb issue id. Optional.
  - **If provided:** groom that specific issue.
  - **If empty:** auto-select the highest-priority issue via `mcp__issuesdb__list_issues(status=open, limit=1)`. If zero results, output "**RESULT: none**" and exit. If running interactively (user present), you may ask which one to groom before proceeding. If running unattended, auto-select without prompting.

## Steps

### 1. Load context
- `mcp__issuesdb__get_issue` for the issue.
- **Resolve the target repo from the issue's `project` field.** Map it to its directory under `/Users/jared/dev/` (e.g. `rentaway` → `/Users/jared/dev/rentaway`, `SRApp` → `/Users/jared/dev/SRApp`, `issuesdb` → `/Users/jared/dev/issuesdb`). This is the only repo step 3 may scan. Do not investigate the issuesdb app repo for an issue whose `project` is anything other than `issuesdb`, no matter how much issuesdb context is in scope.
- Read existing comments. Note any prior questions, decisions, or attempts.

### 2. Assess as-is
Score the issue on these dimensions and call out gaps:

- **Problem clarity**: Is the user-visible problem or desired behavior clear?
- **Scope**: Is the boundary obvious? What's explicitly out of scope?
- **Acceptance criteria**: How will we know it's done? Concrete, testable.
- **Repro / examples** (bugs): exact steps, expected vs. actual, environment.
- **Design hints** (features): mockups, API shape, edge cases considered.
- **Dependencies / blockers**: other issues, infra, decisions.
- **Risk**: data migrations, security surface, breaking changes, public API.

### 3. Investigate the codebase
- Work inside the repo resolved in step 1 (the issue's `project`), not whatever repo happens to be in your working directory or context.
- Spend a small budget here — locate the touchpoints the issue likely affects.
- Note any non-obvious constraints: existing abstractions, feature flags, tests that lock behavior in place.
- Do NOT change code. Grooming is read-only.

### 4. Propose a groomed version
Draft an updated issue body with these sections:

```
## Problem
<what and why, in plain language>

## Acceptance criteria
- [ ] testable bullet 1
- [ ] testable bullet 2

## Out of scope
- ...

## Touchpoints (from codebase scan)
- path/to/file.ts — what changes here

## Open questions
- ...

## Risk / notes
- ...
```

### 5. Decide readiness
Pick one:
- **Ready** — no open questions, criteria are testable. Update the issue body via `mcp__issuesdb__update_issue` with the groomed content **and set `status=ready`**. This removes it from the ungroomed queue and queues it for implementation. If there are existing comments on the issue (i.e., this completes a "needs input" cycle), also call `mcp__issuesdb__add_comment` with: "Grooming complete — description updated above. Earlier comments reflect pre-clarification Q&A and may be superseded."
- **Needs input** — open questions remain. Post the groomed draft *as a comment* via `mcp__issuesdb__add_comment` with the questions surfaced at the top, and tag the requester. Leave `status=open` so it stays in the queue. Don't overwrite the issue body until questions are answered. Comment bodies render as **markdown** in the web UI — use headers, bullets, and code spans freely.
- **Reject / duplicate / won't-fix** — explain in a comment, link related issues, propose closing. Set `status=closed`.

### 6. Report
Output a one-paragraph summary to the user: which path you took, the open questions (if any), and a link to the issue.

### 7. Notify
Call `PushNotification` with a concise message so the requester is alerted on mobile:

- **Ready:** `"Groomed: <issue title> (#<id>) — marked ready for implementation."`
- **Needs input:** `"Grooming paused: <issue title> (#<id>) — <N> question(s) need your input."`
- **Closed:** `"Closed: <issue title> (#<id>) — see issue comment for reasoning."`

This requires Remote Control + "Push when Claude decides" enabled in the Claude.ai app. If not configured the tool call is silently skipped — the command still completes normally.

## Structured output

At the very end of your response, output a machine-parseable result block so orchestrators can consume the outcome. Use exactly this format:

```
## RESULT
- status: <ready|needs-input|closed|none>
- issue_id: <id>
- questions: <N> (only when status=needs-input)
```

Do not include any other text in the RESULT block. Output it as the last thing before the final newline.

## Guardrails

- Don't invent acceptance criteria the requester didn't ask for. Pull from their words; mark inferences as "assumption — confirm?".
- Don't expand scope. If you spot adjacent improvements, list them as separate suggested issues, not part of this one.
- Don't groom into a plan. Grooming defines *what*; planning (in `/work-issuesdb`) defines *how*.


# synced-from: issuesdb-plugin
