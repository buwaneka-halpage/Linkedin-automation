# Codebase Guide for Learners

This document explains how the LinkedIn MCP server works from the ground up — the concepts, the architecture, and every file. No prior MCP or OAuth experience required.

---

## Table of Contents

1. [What is MCP?](#what-is-mcp)
2. [What is OAuth 2.0?](#what-is-oauth-20)
3. [System Architecture](#system-architecture)
4. [How a Request Flows End to End](#how-a-request-flows-end-to-end)
5. [File by File](#file-by-file)
6. [Key Concepts Explained](#key-concepts-explained)
7. [Common Gotchas](#common-gotchas)

---

## What is MCP?

**MCP (Model Context Protocol)** is a standard that lets AI assistants like Claude talk to external services. Think of it as a plugin system — you write a server that exposes "tools", and Claude can call those tools during a conversation.

```
You (in Claude Desktop)
    │
    │  natural language: "Post this to LinkedIn"
    ▼
Claude (AI)
    │
    │  calls tool: linkedin_create_post(text="...")
    ▼
MCP Server (server.py — our code)
    │
    │  HTTP POST to LinkedIn API
    ▼
LinkedIn
```

Claude Desktop communicates with our server over **stdio** (standard input/output) — it literally pipes JSON messages back and forth through the terminal. Our server reads those messages, executes the right function, and writes the result back.

---

## What is OAuth 2.0?

OAuth 2.0 is the industry standard for letting a user grant an app limited access to their account without sharing their password. The "three-legged" variant works like this:

```
         1. "I want access"                2. "Approve this app?"
User ──────────────────────► App ─────────────────────────► LinkedIn
                                                                │
                                                       User logs in
                                                       and clicks Allow
                                                                │
         4. "Here's your token"            3. "Here's a code"  │
User ◄─────────────────────── App ◄─────────────────────────────
```

**The three legs:**
1. User → App: user triggers the flow
2. App → LinkedIn: app redirects user to LinkedIn's login page
3. LinkedIn → App: after approval, LinkedIn sends back an authorization **code** to our local callback server

The app then exchanges that **code** for an **access token** — a secret string it includes in every API request to prove it's allowed.

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│  Claude Desktop                                     │
│                                                     │
│  ┌─────────────┐     stdio (JSON-RPC)               │
│  │   Claude AI  │◄──────────────────────────────┐  │
│  └─────────────┘                               │  │
└───────────────────────────────────────────────│──┘
                                                │
                                    ┌───────────┴──────────┐
                                    │    server.py          │
                                    │  (FastMCP tools)      │
                                    └───────────┬──────────┘
                              ┌─────────────────┼──────────────┐
                              │                 │              │
                   ┌──────────┴──┐   ┌──────────┴──┐  ┌───────┴──────┐
                   │   auth.py   │   │linkedin_api  │  │token_store   │
                   │ OAuth flow  │   │  API calls   │  │tokens.json   │
                   └──────────┬──┘   └──────────┬──┘  └──────────────┘
                              │                 │
                              └────────┬────────┘
                                       │  HTTPS
                                  ┌────┴────┐
                                  │ LinkedIn │
                                  │   API   │
                                  └─────────┘
```

---

## How a Request Flows End to End

### Example: `linkedin_create_post`

```
1. You type in Claude Desktop:
   "Post: Excited to share my new project!"

2. Claude decides to call the tool:
   linkedin_create_post(text="Excited to share my new project!")

3. Claude Desktop writes to server.py's stdin:
   {"jsonrpc":"2.0","method":"tools/call","params":{"name":"linkedin_create_post",...}}

4. server.py receives the message, calls:
   linkedin_api.create_text_post("Excited to share my new project!", "PUBLIC")

5. linkedin_api.py:
   a. Calls auth.get_valid_token()        ← checks tokens.json, refreshes if needed
   b. Gets person URN from tokens.json    ← "urn:li:person:A5_DpY909v"
   c. Builds JSON payload for LinkedIn
   d. POST https://api.linkedin.com/v2/ugcPosts

6. LinkedIn returns:
   HTTP 201 Created
   x-restli-id: urn:li:ugcPost:7234567890

7. linkedin_api.py returns:
   {"post_id": "urn:li:ugcPost:7234567890", "post_url": "https://..."}

8. server.py writes result back to stdout (to Claude Desktop)

9. Claude tells you:
   "Your post has been published! View it here: https://..."
```

---

## File by File

### `config.py` — Configuration loader

**Purpose:** Single place for all constants. Reads your `.env` file.

```python
CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_PORT = int(os.environ.get("LINKEDIN_REDIRECT_PORT", "8080"))
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = "openid profile email w_member_social"
```

**Why a separate file?** All other files import `config` — if you need to change a URL or port, you change it in one place only.

---

### `token_store.py` — Token persistence

**Purpose:** Save and load OAuth tokens to/from `tokens.json`.

Key functions:
- `save_tokens(tokens)` — writes dict to disk as JSON
- `load_tokens()` — reads and returns the dict (or `None`)
- `tokens_valid()` — returns `True` if the access token hasn't expired yet
- `token_status()` — human-readable auth state (used by Claude)

**Why tokens expire:** LinkedIn access tokens last ~60 days. When they expire, the server uses the `refresh_token` to automatically get a new one without making you log in again.

```python
# The expiry is stored as a Unix timestamp (seconds since 1970)
expires_at = tokens.get("expires_at", 0)
remaining = expires_at - time.time()   # seconds remaining
```

---

### `auth.py` — OAuth 2.0 three-legged flow

**Purpose:** Handle the full browser-based login flow and token refresh.

The trickiest file in the project. Key parts:

**Local callback server:**
```python
class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # LinkedIn redirects to http://localhost:8080/callback?code=AUTH_CODE
        # This handler grabs the code from the URL
        params = parse_qs(parsed.query)
        _auth_result["code"] = params.get("code", [None])[0]
```

We spin up a tiny HTTP server on `localhost:8080` in a background thread. LinkedIn needs somewhere to send the user after they approve — this is that "somewhere".

**State parameter (CSRF protection):**
```python
state = secrets.token_urlsafe(16)
```
A random string we send to LinkedIn and expect back. If the value coming back doesn't match what we sent, someone may be trying to hijack the flow — we reject it.

**Flow sequence in `run_oauth_flow()`:**
1. Generate random `state`
2. Start local HTTP server on port 8080
3. Open browser to LinkedIn's auth URL
4. Poll `_auth_result` every 200ms until the callback arrives
5. Shut down local server
6. Exchange code for tokens via POST to LinkedIn
7. Save tokens to disk

---

### `linkedin_api.py` — LinkedIn REST API wrappers

**Purpose:** Clean Python functions that talk to LinkedIn's API. No tokens/auth logic here — it calls `auth.get_valid_token()` and uses the result.

**The `_headers()` function:**
```python
def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_valid_token()}",
        "X-Restli-Protocol-Version": "2.0.0",  # required by LinkedIn
        "Content-Type": "application/json",
    }
```
Every LinkedIn API request needs these three headers.

**Person URN:**
LinkedIn identifies users by a "URN" (Uniform Resource Name): `urn:li:person:A5_DpY909v`. When creating a post, you set `author` to this URN. We cache it in `tokens.json` after login so we don't need to fetch it on every call.

**Creating a post (`create_text_post`):**
```python
payload = {
    "author": "urn:li:person:A5_DpY909v",
    "lifecycleState": "PUBLISHED",
    "specificContent": {
        "com.linkedin.ugc.ShareContent": {
            "shareCommentary": {"text": "Hello LinkedIn!"},
            "shareMediaCategory": "NONE",
        }
    },
    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
}
```
The deeply nested structure is how LinkedIn's UGC (User Generated Content) API was designed. `NONE` means plain text; `ARTICLE` means a link preview.

**Fetching own posts (`get_my_posts`):**
```python
GET /v2/ugcPosts?q=authors&authors=List(urn:li:person:{id})&count=10&sortBy=LAST_MODIFIED
```
Returns a paginated list. We parse each element's `specificContent` to extract the post text, type, and metadata.

---

### `server.py` — FastMCP server

**Purpose:** Define the tools that Claude can call. This is the entry point — Claude Desktop runs this file.

**How FastMCP works:**
```python
mcp = FastMCP("LinkedIn")

@mcp.tool()                          # decorator registers this as a tool
def linkedin_create_post(text: str, visibility: str = "PUBLIC") -> dict:
    """Docstring becomes the tool description Claude reads"""
    ...

mcp.run()                            # starts stdio loop
```

The `@mcp.tool()` decorator does a lot:
- Registers the function name as the tool name
- Uses the docstring as the tool's description (Claude reads this to know when to use it)
- Uses Python type hints to define what parameters Claude should pass
- Handles JSON serialisation of return values automatically

**Error handling pattern:**
Every tool wraps the API call in `try/except` and returns a dict with an `"error"` key instead of raising. This lets Claude tell you what went wrong ("Missing scope", "Token expired") rather than crashing silently.

---

## Key Concepts Explained

### Why stdio transport?

Claude Desktop launches our server as a subprocess and communicates via stdin/stdout. This is the simplest transport — no ports, no HTTP server, no authentication between Claude and our server. The process lifetime is tied to Claude Desktop.

### Why cache the Person URN?

Every post creation needs `urn:li:person:{id}` as the `author` field. Fetching it requires a separate API call to `/v2/userinfo`. By caching it in `tokens.json` after the first login, every subsequent post creation happens in one API call instead of two.

### Why `expires_at` instead of `expires_in`?

LinkedIn returns `expires_in: 5183999` (seconds from now). If we stored that, we'd need to know when we received it to calculate expiry. By converting to `expires_at = time.time() + expires_in` at save time, we always know the absolute expiry date regardless of when we check.

### What is `X-Restli-Protocol-Version: 2.0.0`?

LinkedIn's API is built on a framework called Rest.li. Version 2.0.0 changes how IDs are encoded in request/response bodies and headers. Without this header, some endpoints behave differently or return errors.

---

## Common Gotchas

**Claude Desktop overwrites the config**
If you change a preference in Claude Desktop's UI, it rewrites `claude_desktop_config.json` and may reset `mcpServers: {}`. Re-add the server block manually after any UI settings change.

**Same LinkedIn account logs in every time**
The browser has a session cookie. To switch accounts, log out of LinkedIn in the browser first, then re-run `linkedin_authenticate`.

**`403 Forbidden` on `linkedin_get_my_posts`**
The `r_member_social` scope is needed to read posts. Go to your LinkedIn Developer App → Products → ensure "Share on LinkedIn" is added → re-authenticate.

**Port 8080 already in use**
If something else is running on port 8080, the OAuth callback will fail. Change `LINKEDIN_REDIRECT_PORT` in `.env` to another port (e.g. `8181`) and update your LinkedIn app's redirect URI to match.
