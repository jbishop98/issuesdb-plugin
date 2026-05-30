---
name: triage-issue
description: >
  Triage an issuesdb issue — run the issue-triage subagent and output a VERDICT JSON line for routing
---

# Triage an issuesdb issue

> This skill is for **standalone human-driven routing** — it emits a tier verdict only. The orchestrator does **not** call this skill; it invokes the `issue-triage` **agent** directly because it needs the full structured report (touchpoints + risk_flags), not just the verdict line.

Run the issue-triage subagent on the issuesdb issue (repo root: the current working directory). After the triage report, decide the routing tier and output exactly one final line:

VERDICT {"tier":1|2|3,"size":"trivial|small|medium|large|unscoped","recommendation":"proceed|caution|halt"}

## Tier definitions (canonical)

These are the **single source of truth** for impact tiers. The tables in `orchestrate` and `work-issuesdb` mirror this list — keep them in sync.

- **Tier 1 — Low** — Docs, typos, copy/cosmetic, simple config. Trivial/small size.
- **Tier 2 — Medium** — Bug fixes, new features in non-critical paths. Small/medium size.
- **Tier 3 — High** — Auth, security, data integrity, API contracts, schema changes, perf-critical paths. Medium/large/unscoped size.

When in doubt, go one tier higher. If the issue touches auth, user data, payments, or external APIs anywhere in its call graph, use Tier 3.


# synced-from: issuesdb-plugin
