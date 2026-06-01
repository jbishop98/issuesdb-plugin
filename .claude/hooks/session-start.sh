#!/bin/bash
set -euo pipefail

# Only run in remote/cloud environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

VENV_PATH="$HOME/.venv-issuesdb"
PLUGIN_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

echo "=== issuesdb-plugin session startup ==="

# 1. Create venv and install the issuesdb MCP server package
echo "Installing issuesdb..."
if [ ! -d "$VENV_PATH" ]; then
  python3 -m venv "$VENV_PATH"
fi
"$VENV_PATH/bin/pip" install --quiet --upgrade git+https://github.com/jbishop98/issuesdb.git

# 2. Register MCP server in user-level Claude Code settings (~/.claude/settings.json)
#    so the correct cloud venv path is used regardless of the project .mcp.json.
echo "Configuring issuesdb MCP server..."
mkdir -p "$HOME/.claude"
python3 - << 'PYEOF'
import json, os

settings_path = os.path.join(os.environ["HOME"], ".claude", "settings.json")
venv_python = os.path.join(os.environ["HOME"], ".venv-issuesdb", "bin", "python")

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
echo "Syncing skills..."
python3 "$PLUGIN_DIR/scripts/sync_skills.py" --target claude

# 4. Sync agents from agents/ to ~/.claude/agents/
echo "Syncing agents..."
python3 "$PLUGIN_DIR/scripts/sync_skills.py" --source agents --target claude

echo "=== Setup complete ==="
