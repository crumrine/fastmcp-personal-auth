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
Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS):
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
Requires Node.js. The `mcp-remote` bridge handles the OAuth flow (opens a browser for one-time auth).

### Claude Code
```bash
claude mcp add my-server --transport http "https://your-domain.com/mcp"
```

### Claude mobile (iOS/Android)
Add the connector on claude.ai web (above). It syncs to mobile automatically. You cannot add connectors directly from the mobile app.

## Configuration

```python
auth = PersonalAuthProvider(
    # Required: your public URL (used for OAuth discovery).
    # Must match exactly how clients will reach your server.
    base_url="https://your-domain.com",

    # Optional: password gate on /authorize (default: None)
    # In practice, the domain restriction is the primary security gate.
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

## Implementation guide

### Things that will bite you

These are real issues we hit building this. They're not documented well elsewhere.

**1. DCR must be explicitly enabled**

FastMCP's `ClientRegistrationOptions` defaults to `enabled=False`. Without it, `/register` returns 404 and Claude.ai silently fails to connect. `PersonalAuthProvider` enables this for you.

**2. `base_url` must match your public URL exactly**

The OAuth discovery endpoint at `/.well-known/oauth-authorization-server` advertises endpoints using `base_url`. If this doesn't match how Claude.ai reaches your server (e.g., `http://localhost` vs `https://your-domain.com`), the OAuth flow will fail with redirect mismatches.

**3. Do NOT use FastAPI's `BaseHTTPMiddleware`**

If you wrap your MCP server in FastAPI and add middleware via `@app.middleware("http")` or `BaseHTTPMiddleware`, it will break streaming responses. Streamable HTTP and SSE both fail because the middleware tries to iterate the response body, which asserts on SSE message types. Use raw ASGI middleware instead, or — better — let FastMCP handle everything via `mcp.run()`.

**4. Use `mcp.run()`, not a FastAPI wrapper**

FastMCP's `mcp.run(transport="streamable-http")` sets up all the OAuth endpoints, transport, and routing correctly. If you mount it manually on FastAPI, you'll need to handle path prefixes, lifespan, and well-known endpoints yourself. Just use `mcp.run()`.

**5. Streamable HTTP responses are SSE, not JSON**

Even though the transport is called "streamable-http", tool call responses come back as `text/event-stream` (SSE format), not `application/json`. If you're writing a custom client, parse the `data:` lines:

```python
def parse_sse(text):
    for line in text.split('\n'):
        if line.startswith('data: '):
            return json.loads(line[6:])
```

**6. Notifications return 202 with empty body**

MCP notifications (like `notifications/initialized`) return HTTP 202 with no body. Don't try to parse the response as JSON.

**7. Tool names matter more than you think**

If your tools are named `add_memory`, `search_memories`, etc., Claude will prefer its built-in memory feature over your MCP tools. Use distinctive prefixed names: `vault_save`, `myapp_search`, `mem0_list`. Also set strong `instructions` on the FastMCP server telling Claude to prefer your tools.

**8. Neon/serverless Postgres drops idle connections**

If your tools use Neon Postgres (or similar serverless databases), don't create a single database connection at startup and reuse it. The connection will go stale and you'll get `InterfaceError: connection already closed`. Create a fresh connection per tool call.

**9. Claude.ai connects but never calls tools**

Check your server logs. If you see `ListToolsRequest` but never `CallToolRequest`, Claude is discovering your tools but choosing not to use them. This usually means:
- Tool names collide with built-in features (see point 7)
- Tool descriptions are too generic
- The server `instructions` aren't directive enough

Fix by being explicit in instructions: *"ALWAYS use these tools instead of built-in memory."*

### Required OAuth endpoints

Claude.ai expects all of these to work. `PersonalAuthProvider` + FastMCP set them up automatically:

| Endpoint | Purpose |
|---|---|
| `/.well-known/oauth-authorization-server` | OAuth metadata discovery |
| `/.well-known/oauth-protected-resource/mcp` | Resource metadata (points to auth server) |
| `/register` | Dynamic Client Registration (DCR) |
| `/authorize` | Authorization (redirect-based) |
| `/token` | Token exchange (auth code → access token) |
| `/mcp` | Your MCP endpoint (requires Bearer token) |

### Verifying your setup

Run these curl commands to check each piece:

```bash
# 1. OAuth discovery (should return JSON with registration_endpoint)
curl -s https://your-domain.com/.well-known/oauth-authorization-server | python3 -m json.tool

# 2. DCR (should return client_id)
curl -s https://your-domain.com/register -X POST \
  -H "Content-Type: application/json" \
  -d '{"client_name":"test","redirect_uris":["https://claude.ai/api/mcp/auth_callback"]}'

# 3. MCP endpoint (should return 401)
curl -s -o /dev/null -w "%{http_code}" https://your-domain.com/mcp

# 4. Protected resource metadata
curl -s https://your-domain.com/.well-known/oauth-protected-resource/mcp | python3 -m json.tool
```

If all four pass, add the connector on claude.ai.

## Token persistence

Tokens are saved to `{state_dir}/oauth_tokens.json` (default `.oauth-state/oauth_tokens.json`). This file contains registered clients, access tokens, and refresh tokens.

For a personal server this is fine. For multi-user deployments, subclass and override `_load_state`/`_save_state` with a database backend.

**Docker**: mount the state dir as a volume so tokens survive container recreation:
```yaml
volumes:
  - ./oauth-state:/app/.oauth-state
```

## Deployment

Any setup that exposes your server via HTTPS works:

- **Cloudflare Tunnel** — `cloudflared tunnel` pointing to `localhost:8050`
- **ngrok** — `ngrok http 8050`
- **Caddy/nginx** — reverse proxy with automatic TLS
- **Docker** — bind to `127.0.0.1:8050`, tunnel handles external access

HTTPS is required — Claude.ai won't connect to plain HTTP (except localhost for development).

## Troubleshooting

**Claude.ai says "error connecting"**
- Verify `/.well-known/oauth-authorization-server` returns JSON with a `registration_endpoint` field
- Verify `/register` accepts POST requests and returns a `client_id`
- Make sure `base_url` matches your actual public URL exactly (including `https://`)
- Check that your server is reachable from the internet (not just localhost)

**Claude Desktop says "command" is required**
- Your version of Claude Desktop doesn't support remote MCP directly. Use the `npx mcp-remote` bridge shown in the connection instructions above.

**OAuth works but tools return errors**
- Check server logs for the actual exception
- If you see `connection already closed`, your database connection went stale (see implementation guide point 8)

**Tokens lost after restart**
- Make sure `state_dir` points to a persistent path
- In Docker, the state dir must be a mounted volume, not inside the container's ephemeral filesystem

## License

MIT
