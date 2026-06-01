#!/bin/bash
set -euo pipefail

# Only run in remote/cloud environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

VENV_PATH="${ISSUESDB_VENV_PATH:-$HOME/.venv-issuesdb}"
PLUGIN_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ISSUESDB_PIP_URL="${ISSUESDB_PIP_URL:-git+https://github.com/jbishop98/issuesdb.git}"
SYNC_SCRIPT="$PLUGIN_DIR/scripts/sync_skills.py"

echo "=== issuesdb-plugin session startup ==="

# 1. Create venv and install the issuesdb MCP server package
echo "Installing issuesdb from $ISSUESDB_PIP_URL..."
if [ ! -d "$VENV_PATH" ]; then
  python3 -m venv "$VENV_PATH"
fi
"$VENV_PATH/bin/pip" install --quiet --upgrade "$ISSUESDB_PIP_URL" || {
  echo "Error: failed to install issuesdb" >&2
  exit 1
}

# 2. Register MCP server in user-level Claude Code settings (~/.claude/settings.json).
#    ${ISSUESDB_DATABASE_URL} uses Claude Code MCP env syntax — expanded at server-launch
#    time, not baked into the JSON, so the value stays current across sessions.
if [ -z "${ISSUESDB_DATABASE_URL:-}" ]; then
  echo "Warning: ISSUESDB_DATABASE_URL is not set — MCP server will start without a database connection" >&2
fi
echo "Configuring issuesdb MCP server..."
mkdir -p "$HOME/.claude"
ISSUESDB_VENV_PATH="$VENV_PATH" python3 - << 'PYEOF'
import json, os

settings_path = os.path.join(os.environ["HOME"], ".claude", "settings.json")
venv_python = os.path.join(os.environ["ISSUESDB_VENV_PATH"], "bin", "python")

settings = {}
if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

settings.setdefault("mcpServers", {})["issuesdb"] = {
    "command": venv_python,
    "args": ["-m", "issuesdb.mcp_server"],
    "env": {"ISSUESDB_DATABASE_URL": "${ISSUESDB_DATABASE_URL}"}
}

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print(f"  -> MCP server registered at {venv_python}")
PYEOF

# 3. Sync skills from commands/ to ~/.claude/skills/
if [ ! -f "$SYNC_SCRIPT" ]; then
  echo "Error: sync_skills.py not found at $SYNC_SCRIPT" >&2
  exit 1
fi
echo "Syncing skills..."
python3 "$SYNC_SCRIPT" --target claude || {
  echo "Error: skills sync failed" >&2
  exit 1
}

# 4. Sync agents from agents/ to ~/.claude/agents/
echo "Syncing agents..."
python3 "$SYNC_SCRIPT" --source agents --target claude || {
  echo "Error: agents sync failed" >&2
  exit 1
}

echo "=== Setup complete ==="
