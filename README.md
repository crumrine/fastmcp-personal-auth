# fastmcp-personal-auth

A drop-in OAuth 2.1 auth provider for [FastMCP](https://github.com/jlowin/fastmcp) that makes your personal MCP server work on **every Claude platform** — web, mobile, Desktop, and Code.

No external identity provider (Google, GitHub, Auth0) required.

## Why this exists

FastMCP ships with two auth options:

| Provider | Persistence | Security | External IdP required |
|---|---|---|---|
| `InMemoryOAuthProvider` | None (test only) | None (auto-approves everything) | No |
| `OAuthProxy` | Yes | Full OAuth | **Yes** (Google, GitHub, etc.) |

Neither works for the common case: **"I have a personal MCP server and I want Claude.ai and Claude mobile to connect to it securely."**

`PersonalAuthProvider` fills that gap:

| | Persistence | Security | External IdP required |
|---|---|---|---|
| **`PersonalAuthProvider`** | File-backed (survives restarts) | Domain-restricted + optional password | **No** |

## Quick start

```bash
pip install 'fastmcp[auth]'
```

```python
from fastmcp import FastMCP
from personal_auth import PersonalAuthProvider

auth = PersonalAuthProvider(
    base_url="https://your-domain.com",  # your public URL
)

mcp = FastMCP(name="my-server", auth=auth)

@mcp.tool
def hello(name: str) -> str:
    return f"Hello, {name}!"

mcp.run(transport="streamable-http", host="0.0.0.0", port=8050)
```

That's it. Your server now has:
- OAuth 2.1 with Dynamic Client Registration (DCR) and PKCE
- `.well-known` discovery endpoints Claude.ai expects
- Streamable HTTP transport
- Tokens persisted to `.oauth-state/oauth_tokens.json`
- Authorization restricted to `claude.ai`, `claude.com`, and `localhost` by default

## Connecting Claude clients

### Claude.ai (web) — syncs to mobile automatically
```
Settings → Connectors → Add custom connector → URL: https://your-domain.com/mcp
```

### Claude Desktop
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://your-domain.com/mcp"]
    }
  }
}
```

### Claude Code
```bash
claude mcp add my-server --transport http "https://your-domain.com/mcp"
```

## Configuration

```python
auth = PersonalAuthProvider(
    # Required: your public URL (used for OAuth discovery)
    base_url="https://your-domain.com",

    # Optional: password gate on /authorize (default: None)
    # When set, provides an extra layer beyond domain restriction.
    # In practice, the domain restriction is the primary gate —
    # only claude.ai/localhost can complete the OAuth flow.
    password="my-secret",

    # Optional: allowed redirect domains (default shown below)
    # Only these domains can complete the OAuth authorization flow.
    # Set to None to allow all domains (not recommended).
    allowed_redirect_domains=["claude.ai", "claude.com", "localhost"],

    # Optional: access token lifetime (default: 30 days)
    access_token_expiry_seconds=30 * 24 * 60 * 60,

    # Optional: directory for token persistence (default: ".oauth-state")
    state_dir=".oauth-state",
)
```

## How the security works

1. **DCR is open** — any client can register (required by Claude.ai's OAuth flow)
2. **`/authorize` is restricted** — only redirect URIs matching `allowed_redirect_domains` are approved. A random person hitting your server can register a client, but they can't get a token because their redirect URI won't match `claude.ai` or `localhost`
3. **Tokens are opaque** — random hex strings, not JWTs with extractable claims
4. **Refresh tokens don't expire** — access tokens last 30 days and can be refreshed indefinitely
5. **Tokens persist to disk** — you don't re-auth after server restarts

## Token persistence

Tokens are saved to `{state_dir}/oauth_tokens.json` (default `.oauth-state/oauth_tokens.json`). This file contains:
- Registered clients
- Access tokens
- Refresh tokens

For a personal server this is fine. For multi-user deployments, you'd want to swap to a database-backed store by subclassing and overriding `_load_state`/`_save_state`.

## Deployment

Any setup that exposes your server via HTTPS works. Common options:

- **Cloudflare Tunnel** — `cloudflared tunnel` pointing to `localhost:8050`
- **ngrok** — `ngrok http 8050`
- **Caddy/nginx** — reverse proxy with automatic TLS
- **Docker** — bind to `127.0.0.1:8050`, tunnel handles external access

HTTPS is required — Claude.ai won't connect to HTTP endpoints (except localhost).

## Troubleshooting

**Claude.ai says "error connecting"**
- Check that `/.well-known/oauth-authorization-server` returns valid JSON with a `registration_endpoint`
- Verify `/register` accepts POST requests
- Make sure your `base_url` matches your actual public URL exactly

**Tools aren't being called**
- Claude may prefer its built-in memory over tools named `add_memory`/`search_memories`. Use distinctive names (e.g. `vault_save`, `vault_search`)
- Try explicit prompts: "Use the [tool_name] tool to..."
- Check server logs for `CallToolRequest` — if you only see `ListToolsRequest`, Claude is discovering but not using your tools

**Tokens lost on restart**
- Make sure `state_dir` points to a persistent volume (not inside a container's ephemeral filesystem)
- In Docker, mount the state dir: `volumes: ["./oauth-state:/app/.oauth-state"]`

## License

MIT
