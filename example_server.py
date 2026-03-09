"""
Minimal example: a personal MCP server with OAuth that works on
Claude.ai, Claude mobile, Claude Desktop, and Claude Code.

Run:
    pip install 'fastmcp[auth]'
    python example_server.py

Then add as a connector on claude.ai:
    Settings → Connectors → Add custom connector → https://your-domain.com/mcp
"""

import os
from fastmcp import FastMCP
from personal_auth import PersonalAuthProvider

auth = PersonalAuthProvider(
    base_url=os.environ.get("BASE_URL", "http://localhost:8050"),
)

mcp = FastMCP(
    name="my-personal-server",
    instructions="A personal MCP server with tools.",
    auth=auth,
)


@mcp.tool
def greet(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@mcp.tool
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8050)
