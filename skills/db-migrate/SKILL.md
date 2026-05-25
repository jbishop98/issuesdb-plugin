---
name: db-migrate
description: Safely add schema changes to schema_postgres.sql following issuesdb conventions
---

## Schema migration rules for issuesdb

Schema changes go directly into `schema_postgres.sql` — there is no migrations directory. `init_db()` in `db.py` splits this file on `;;` and executes statements sequentially.

### CHECK constraint enum values

**Always add new enum values to the first constraint block.** Never add a separate migration block for a new value — if the first block drops and re-creates the constraint without the new value, it will fail with `CheckViolation` because existing rows already use that value.

**Bad:**
```sql
ALTER TABLE triggers ADD CONSTRAINT triggers_type_check CHECK (type IN ('groom', 'work', 'review'));;
-- ... later in the file ...
ALTER TABLE triggers DROP CONSTRAINT triggers_type_check;;
ALTER TABLE triggers ADD CONSTRAINT triggers_type_check CHECK (type IN ('groom', 'work', 'review', 'orchestrate'));;
```

**Good:**
```sql
ALTER TABLE triggers ADD CONSTRAINT triggers_type_check CHECK (type IN ('groom', 'work', 'review', 'orchestrate'));;
```

### Testing schema changes

Use the Neon MCP to test migrations safely on an isolated branch before applying to production:

1. `prepare_database_migration` — creates a Neon branch and validates the SQL
2. `complete_database_migration` — applies to the target branch

Or test locally against the test database:
```bash
source ~/dev/.venv-issuesdb/bin/activate && \
ISSUESDB_DATABASE_URL="$ISSUESDB_TEST_DATABASE_URL" \
  python3 -c "import sys; sys.path.insert(0, '/Users/jared/dev'); from issuesdb.db import init_db; init_db()"
```

### Statement delimiter

Use `;;` (double semicolon) as the statement delimiter, not `;`. The `init_db()` splitter uses `;;` as the separator.


# synced-from: issuesdb-plugin
