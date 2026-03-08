# Codebase Guide — LinkedIn MCP Server

This guide explains how the codebase is structured, why each file exists, and how data flows through the system. Written for developers learning Python, APIs, or MCP for the first time.

---

## Big Picture

```
Claude Desktop  (chat UI)
      |
      |  MCP protocol (JSON-RPC over stdio)
      v
server.py             <- public interface, 7 MCP tools
      |
      |---> auth.py          <- OAuth 2.0 flow + token refresh
      |          |
      |---> linkedin_api.py  <- LinkedIn REST API wrappers
                 |
          token_store.py     <- read/write tokens.json
                 |
           config.py         <- loads .env
```

**The rule:** each layer only talks to the layer below it. `server.py` never touches `tokens.json` directly — it goes through `linkedin_api.py` → `auth.py` → `token_store.py`.

---

## File-by-File Walkthrough

### `config.py` — The Foundation

Loads `CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_PORT` from `.env` using `python-dotenv`. Defines constants: `AUTH_URL`, `TOKEN_URL`, `API_BASE`, `SCOPES`.

**Why it exists:** every other file needs these values. Centralising them means you only change one file when switching environments.

**Key concept — environment variables:** instead of hardcoding secrets in source code (which would get committed to git), `os.environ.get()` reads from the OS or a `.env` file at runtime. The `.env` file is gitignored so secrets never reach the repo.

---

### `token_store.py` — Persisting Login State

Four functions:
- `save_tokens(tokens)` — writes `tokens.json`
- `load_tokens()` — reads `tokens.json`, returns `None` if missing
- `tokens_valid()` — returns `True` if access token is not expired
- `token_status()` — human-readable dict for the `linkedin_token_status` tool

**Why it exists:** OAuth access tokens expire (~60 days for LinkedIn). If we stored them only in memory, you would need to re-authenticate every time Claude Desktop restarted. A JSON file keeps the session alive across restarts.

**Key concept — token expiry:** every OAuth token has an `expires_in` field (seconds from now). We store `expires_at = time.time() + expires_in` — an absolute Unix timestamp — so we can check `time.time() < expires_at` later without doing time arithmetic.

---

### `auth.py` — The OAuth 2.0 Dance

Implements the **three-legged OAuth 2.0 Authorization Code Flow**.

#### Why "three-legged"?

Three parties are involved:
1. **Your app** (this server) — wants permission
2. **LinkedIn** — owns the resource
3. **You** (the user) — must consent in a browser

#### The flow

```
Your app                   Browser (you)              LinkedIn
    |                           |                          |
    |---- 1. Build auth URL --->|                          |
    |                           |---- 2. GET /authorize -->|
    |                           |<--- 3. Show login page --|
    |                           |---- 4. Submit login ---->|
    |                           |<--- 5. Redirect to ------|
    |                           |   localhost:8080/callback|
    |<--- 6. Callback hits -----|                          |
    |     local HTTP server                                |
    |---- 7. POST /accessToken with code ---------------->|
    |<--- 8. access_token + refresh_token ----------------|
    |---- 9. Save tokens to disk                          |
```

#### Key parts of `auth.py`

**`_CallbackHandler`** — a tiny HTTP server (using Python's built-in `http.server`) that listens on `localhost:8080`. When LinkedIn redirects the browser to `/callback?code=XYZ`, `do_GET()` fires and captures `code` and `state` from the URL into the module-level `_auth_result` dict.

**`_start_callback_server()`** — creates the `HTTPServer` and runs it in a **daemon thread** (a background thread that dies automatically when the main process exits — no manual cleanup needed).

**`run_oauth_flow()`** — orchestrates everything:
1. Generates a random `state` token (CSRF protection — if state does not match on callback, the flow is rejected)
2. Starts the local callback server
3. Opens the browser to LinkedIn's auth URL
4. Polls `_auth_result` every 200ms for up to 5 minutes
5. Validates state, exchanges code for tokens, saves to disk

**`get_valid_token()`** — called before every API request. If the token expires within 5 minutes, it silently calls `refresh_access_token()`. This is why you never re-authenticate after the first time.

---

### `linkedin_api.py` — Talking to LinkedIn

All functions follow this pattern:

```python
def some_api_call(...) -> dict:
    resp = httpx.get/post(url, headers=_headers(), ...)
    resp.raise_for_status()   # raises on 4xx/5xx
    return resp.json()
```

**`_headers()`** builds three required headers for every request:
- `Authorization: Bearer {token}` — proves your identity
- `X-Restli-Protocol-Version: 2.0.0` — LinkedIn's REST.li framework version (required)
- `Content-Type: application/json` — signals a JSON body

#### Creating a post — the ugcPosts payload

```python
{
    "author": "urn:li:person:ABC123",
    "lifecycleState": "PUBLISHED",
    "specificContent": {
        "com.linkedin.ugc.ShareContent": {   # fully-qualified Java class name
            "shareCommentary": {"text": "..."},
            "shareMediaCategory": "NONE",
        }
    },
    "visibility": {
        "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
    }
}
```

The `com.linkedin.ugc.ShareContent` key is a fully-qualified Java class name from LinkedIn's internal type system, exposed through their REST.li framework. You use it exactly as-is.

#### Reading posts — `GET /v2/ugcPosts`

```python
params = {
    "q": "authors",             # which index to query
    "authors": "List(urn:...)", # REST.li typed list syntax
    "count": 10,
    "sortBy": "LAST_MODIFIED",
}
```

The `List(...)` syntax is REST.li's way of encoding a typed list as a query parameter — it is not standard URL encoding.

---

### `server.py` — The MCP Layer

The public interface that Claude Desktop calls. Uses **FastMCP**, which:
1. Converts Python functions into MCP tools
2. Reads docstrings to generate tool descriptions (what Claude reads to pick the right tool)
3. Uses type hints to validate inputs
4. Handles the stdio JSON-RPC protocol automatically

```python
mcp = FastMCP("LinkedIn")

@mcp.tool()
def linkedin_create_post(text: str, visibility: str = "PUBLIC") -> dict:
    """
    Publish a text post to your LinkedIn feed.
    ...
    """
    ...
```

The `@mcp.tool()` decorator registers the function. **Good docstrings = Claude picks the right tool correctly.**

**Why keep `server.py` thin?** Each tool validates input then delegates to `linkedin_api.py`. This means you could add a CLI, a REST API, or automated tests that reuse `linkedin_api.py` without touching the MCP layer.

---

## Data Flow: Creating a Post

```
Claude Desktop calls linkedin_create_post(text="Hello LinkedIn!")
  |
  v
server.py: validate text is not empty
  |
  v
linkedin_api.create_text_post("Hello LinkedIn!", "PUBLIC")
  |
  |-> _headers()
  |     -> auth.get_valid_token()
  |           -> token_store.load_tokens()  -> reads tokens.json
  |           -> check expiry, refresh if needed
  |           -> return "eyJhbG..."
  |-> _get_person_urn() -> read from tokens.json (cached)
  |-> POST https://api.linkedin.com/v2/ugcPosts
  |-> read post_id from x-restli-id response header
  v
return {"post_id": "...", "post_url": "https://www.linkedin.com/feed/update/..."}
  |
  v
Claude Desktop displays the post URL
```

---

## Data Flow: OAuth Authentication

```
Claude Desktop calls linkedin_authenticate()
  |
  v
auth.run_oauth_flow()
  |-> generate random state ("vq3O2Ap...") for CSRF protection
  |-> start _CallbackHandler on localhost:8080 (daemon thread)
  |-> open browser to LinkedIn /authorize URL
  |-> poll _auth_result every 200ms for up to 5 minutes...
  |
  |   [User logs in to LinkedIn in browser]
  |   [LinkedIn redirects to localhost:8080/callback?code=XYZ&state=...]
  |   _CallbackHandler.do_GET() fires, stores code + state in _auth_result
  |   Browser displays "Authorization successful!"
  |
  |-> poll detects _auth_result["code"] is set
  |-> verify state matches (CSRF check)
  |-> POST https://www.linkedin.com/oauth/v2/accessToken
  |     with code, client_id, client_secret, redirect_uri
  |     response: access_token, refresh_token, expires_in
  |-> add expires_at = time.time() + expires_in
  |-> token_store.save_tokens(tokens) -> write tokens.json
  |
  v
call get_profile() to cache person URN in tokens.json
  |
  v
Claude Desktop: "Authenticated successfully as Buwaneka Halpage."
```

---

## Key Python Concepts Used

| Concept | Where | What it does |
|---------|-------|--------------|
| `threading.Thread(daemon=True)` | `auth.py` | Callback server runs in background; dies when main process exits |
| `@decorator` syntax | `server.py` | `@mcp.tool()` registers functions without modifying their code |
| `dict \| None` type hint | `token_store.py` | Union type — returns a dict or None |
| `{**a, **b}` dict unpacking | `auth.py` | Merges two dicts; right-side keys win on conflict |
| `resp.raise_for_status()` | `linkedin_api.py` | Throws immediately on HTTP 4xx/5xx; prevents silent failures |
| `time.time()` | `token_store.py` | Unix timestamp (seconds since 1970); comparable across restarts |

---

## Common Extension Points

**Add a new LinkedIn API tool:**
1. Write a function in `linkedin_api.py` that calls the endpoint
2. Add a `@mcp.tool()` wrapper in `server.py` with a clear docstring
3. Restart Claude Desktop — FastMCP registers it automatically

**Swap the token storage backend:**
Only `token_store.py` needs to change. The four function signatures stay the same, but the implementation could use OS keychain, a database, or encrypted storage. Nothing else in the codebase changes.

**Add a new OAuth scope:**
1. Add the scope string to `SCOPES` in `config.py`
2. Enable the corresponding LinkedIn product in the Developer Portal
3. Delete `tokens.json` and re-run `linkedin_authenticate` — the user will consent to the new scope
