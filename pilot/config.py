"""Runtime configuration, assembled from environment plus CLI overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_MCP_URL = "https://issuesdb-mcp.onrender.com/mcp"
DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class Config:
    mcp_url: str = DEFAULT_MCP_URL
    mcp_secret: str = ""
    anthropic_api_key: str = ""
    model: str = DEFAULT_MODEL
    dispatch: str = "opencode"  # "opencode" | "claude"
    plan_dir: Path = Path("~/dev").expanduser()
    dry_run: bool = False
    timeout: int = 3600
    session_ts: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            mcp_url=os.environ.get("ISSUESDB_MCP_URL", DEFAULT_MCP_URL),
            mcp_secret=os.environ.get("ISSUESDB_MCP_SECRET", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get("PILOT_MODEL", DEFAULT_MODEL),
        )

    def plan_path(self) -> Path:
        ts = self.session_ts or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_ts = ts
        return self.plan_dir / f"DELIVERY_PLAN-{ts}.md"
