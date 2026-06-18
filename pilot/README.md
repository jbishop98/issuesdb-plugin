# pilot (Python)

A Python port of the `pilot` agent (`agents/pilot.md`): a delivery planner and
executor for issuesdb. It loads issues, classifies risk tiers, maps
dependencies, sequences them into ordered delivery batches, writes a
`DELIVERY_PLAN`, then executes each batch by dispatching `/orchestrate`.

## Why a hybrid

The deterministic plumbing — loading issues, parsing `#123` references,
sequencing/bundling batches, rendering the plan, dispatching, and parsing
outcomes — is plain Python (reproducible and unit-tested). Three narrow judgment
steps delegate to an LLM via forced-JSON tool calls:

| Step | Where |
|---|---|
| Assess readiness (is an open issue clear enough?) | `classify.assess_readiness` |
| Classify risk tier (1/2/3) | `classify.classify_tiers` |
| Infer structural dependencies | `classify.infer_dependencies` |

All heavyweight agent work stays behind `/orchestrate`, which the pilot shells
out to. The guardrail "never dispatch `/work-issuesdb`" is structural here —
there is no such code path.

## Install

```bash
pip install -e .          # from the repo root; provides the `pilot` command
```

Requires `ISSUESDB_MCP_SECRET` and `ANTHROPIC_API_KEY` (the latter unless
`--no-llm`).

## Usage

```bash
pilot 142 143 150         # specific issue IDs
pilot rentaway            # every open/ready issue in a project
pilot                     # full backlog (all projects)

pilot rentaway --dry-run            # write the plan, don't execute
pilot 142 --dispatch claude         # dispatch via `claude -p`
pilot --help                        # full option/flag/env documentation
```

It can run headless from cron/CI (no Claude Code session needed), the same way
`scripts/work-queue.sh` drives `/orchestrate`.

## Tests

```bash
pytest                    # deterministic core + offline end-to-end
```
