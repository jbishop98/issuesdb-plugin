#!/bin/bash
set -euo pipefail

# Only run in remote/cloud environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PLUGIN_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SYNC_SCRIPT="$PLUGIN_DIR/scripts/sync_skills.py"
ISSUESDB_MCP_URL="${ISSUESDB_MCP_URL:-https://issuesdb-mcp.onrender.com/mcp}"

echo "=== issuesdb-plugin session startup ==="

# 1. Register remote MCP server in user-level Claude Code settings.
#    Claude Code handles OAuth automatically when connecting to the URL.
echo "Configuring issuesdb MCP server ($ISSUESDB_MCP_URL)..."
mkdir -p "$HOME/.claude"
ISSUESDB_MCP_URL="$ISSUESDB_MCP_URL" python3 - << 'PYEOF'
import json, os

settings_path = os.path.join(os.environ["HOME"], ".claude", "settings.json")

settings = {}
if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

settings.setdefault("mcpServers", {})["issuesdb"] = {
    "url": os.environ["ISSUESDB_MCP_URL"]
}

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
url = os.environ["ISSUESDB_MCP_URL"]
print(f"  -> MCP server registered at {url}")
PYEOF

# 2. Sync skills from commands/ to ~/.claude/skills/
if [ ! -f "$SYNC_SCRIPT" ]; then
  echo "Error: sync_skills.py not found at $SYNC_SCRIPT" >&2
  exit 1
fi
echo "Syncing skills..."
python3 "$SYNC_SCRIPT" --target claude || {
  echo "Error: skills sync failed" >&2
  exit 1
}

# 3. Sync agents from agents/ to ~/.claude/agents/
echo "Syncing agents..."
python3 "$SYNC_SCRIPT" --source agents --target claude || {
  echo "Error: agents sync failed" >&2
  exit 1
}

echo "=== Setup complete ==="
