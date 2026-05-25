---
name: run-tests
description: Run the issuesdb pytest suite against the Neon test branch
---

Requires `ISSUESDB_TEST_DATABASE_URL` to be set and contain `test` or `branch` in the URL. The conftest guard will refuse to run if it's absent or points to production.

Run from `~/dev` (the venv lives at `~/dev/.venv-issuesdb`):

```bash
source ~/dev/.venv-issuesdb/bin/activate && \
ISSUESDB_TEST_DATABASE_URL="$ISSUESDB_TEST_DATABASE_URL" \
  python -m pytest ~/dev/issuesdb/tests/ \
  --ignore=~/dev/issuesdb/tests/test_issue_detail.py \
  --ignore=~/dev/issuesdb/tests/test_opencode_review.py \
  -v
```

`test_issue_detail.py` and `test_opencode_review.py` are excluded — they are skipped in CI and require additional setup.


# synced-from: issuesdb-plugin
