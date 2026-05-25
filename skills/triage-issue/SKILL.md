---
name: triage-issue
description: >
  Triage an issuesdb issue — run the issue-triage subagent and output a VERDICT JSON line for routing
---

# Triage an issuesdb issue

Run the issue-triage subagent on the issuesdb issue (repo root: the current working directory). After the triage report, decide the routing tier and output exactly one final line:

VERDICT {"tier":1|2|3,"size":"trivial|small|medium|large|unscoped","recommendation":"proceed|caution|halt"}

Tier assignment:
- **Tier 1** — Docs, typos, copy/cosmetic, simple config changes. Trivial/small size.
- **Tier 2** — Bug fixes, new features in non-critical paths. Small/medium size.
- **Tier 3** — Auth, security, data integrity, API contracts, schema changes, perf-critical paths. Medium/large/unscoped size.

When in doubt, go one tier higher. If the issue touches auth, user data, payments, or external APIs, use Tier 3.


# synced-from: issuesdb-plugin
