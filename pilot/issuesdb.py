"""issuesdb MCP client — pilot step 1 (load) and step 7 (status updates).

Talks to the issuesdb MCP server over streamable HTTP using the same endpoint
and Bearer secret as .mcp.json. The MCP SDK is async; this wraps it in a small
synchronous facade since the pilot makes only a handful of calls.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .models import Issue


class Tracker:
    """Synchronous wrapper over the issuesdb MCP server."""

    def __init__(self, url: str, secret: str):
        self._url = url
        self._headers = {"Authorization": f"Bearer {secret}"} if secret else {}

    # --- public API -------------------------------------------------------
    def get_issue(self, issue_id: int) -> Issue:
        data = self._call("get_issue", {"id": issue_id})
        return Issue.from_dict(_unwrap(data))

    def list_issues(self, project: str | None = None, status: str | None = None,
                    limit: int | None = None) -> list[Issue]:
        args: dict[str, Any] = {}
        if project:
            args["project"] = project
        if status:
            args["status"] = status
        if limit:
            args["limit"] = limit
        data = self._call("list_issues", args)
        return [Issue.from_dict(d) for d in _as_list(data)]

    def list_projects(self) -> list[str]:
        data = self._call("list_projects", {})
        items = _as_list(data)
        out: list[str] = []
        for item in items:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                out.append(item.get("name") or item.get("project") or "")
        return [p for p in out if p]

    def update_issue(self, issue_id: int, **fields: Any) -> None:
        self._call("update_issue", {"id": issue_id, **fields})

    def add_comment(self, issue_id: int, body: str) -> None:
        self._call("add_comment", {"issue_id": issue_id, "body": body})

    # --- transport --------------------------------------------------------
    def _call(self, tool: str, arguments: dict) -> Any:
        return asyncio.run(self._call_async(tool, arguments))

    async def _call_async(self, tool: str, arguments: dict) -> Any:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'mcp' package is required to reach issuesdb. "
                "Install it with: pip install mcp"
            ) from exc

        async with streamablehttp_client(self._url, headers=self._headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return _extract_payload(result)


def _extract_payload(result: Any) -> Any:
    """Pull JSON out of an MCP CallToolResult.

    Tolerates the several wire shapes different mcp-server versions emit for a
    tool annotated ``-> str``:

    * plain text block holding a JSON array/object (older servers);
    * ``structuredContent`` set, with the real value wrapped as ``{"result": …}``
      because primitive returns get wrapped (mcp >= ~1.10);
    * a text block whose JSON is *double-encoded* (a JSON string that itself
      decodes to more JSON), which otherwise yields a bare ``str`` and trips up
      callers expecting a dict/list.
    """
    # Prefer structuredContent — it's the typed payload when the server sets it.
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        # Primitive returns are wrapped as {"result": <value>}.
        value = structured["result"] if set(structured) == {"result"} else structured
        return _maybe_reparse(value)

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            try:
                return _maybe_reparse(json.loads(text))
            except json.JSONDecodeError:
                return text
    return None


def _maybe_reparse(value: Any) -> Any:
    """Decode one extra JSON layer if the value is itself a JSON string.

    Some server versions double-encode the payload, so ``json.loads`` returns a
    ``str`` that still needs parsing into the real list/dict.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _as_list(data: Any) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("issues", "results", "items", "data", "projects"):
            if isinstance(data.get(key), list):
                return data[key]
    return [data]


def _unwrap(data: Any) -> dict:
    if isinstance(data, dict) and isinstance(data.get("issue"), dict):
        return data["issue"]
    return data if isinstance(data, dict) else {}
