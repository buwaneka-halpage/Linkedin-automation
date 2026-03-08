# Codebase Guide — LinkedIn MCP Server

This guide explains how the codebase is structured, why each file exists, and how data flows through the system. Written for developers learning Python, APIs, or MCP for the first time.

---

## Big Picture

```
Claude Desktop  (chat UI)
      |
      |  MCP protocol (JSON-RPC over stdio)
      v
server.py                  <- public interface, 9 MCP tools
      |
      |---> auth.py             <- OAuth 2.0 flow + token refresh
      |          |
      |---> linkedin_api.py     <- routes requests to right backend
      |          |
      |          |---> httpx (official REST API) -- for posting
      |          |---> voyager.py               -- for reading + jobs + outreach
      |          |---> posts_store.py            -- local fallback
      |
      |---> job_scorer.py       <- Module 4: Gemini job scoring (also used by MCP tool)
      |
      token_store.py        <- read/write tokens.json (OAuth)
      config.py             <- loads .env
      llm.py                <- thin Gemini wrapper (all LLM calls)

Standalone scripts (triggered by OS scheduler / Task Scheduler):
  scheduler.py   <- Module 2: generate post with Gemini, publish, exit
  outreach.py    <- Module 3: search + connect people via Voyager, rate-limited 5/day
  job_scorer.py  <- Module 4: also runnable as CLI (py -3 job_scorer.py --keywords "...")
```

**Two authentication tracks run in parallel:**
- **OAuth 2.0** (Client ID + Secret) — used by `auth.py` for creating posts and fetching profile
- **Voyager API** (Email + Password) — used by `voyager.py` for reading posts, searching jobs, and sending connection requests

LinkedIn removed the `r_member_social` (read posts) scope from the free OAuth tier, which is why two separate auth methods are needed.

---

## File-by-File Walkthrough

### `config.py` — The Foundation

Loads `CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_PORT` from `.env` using `python-dotenv`. Defines constants: `AUTH_URL`, `TOKEN_URL`, `API_BASE`, `SCOPES`.

**Why it exists:** every other file needs these values. Centralising them means you only change one file when switching environments.

**Key concept — environment variables:** instead of hardcoding secrets in source code (which would get committed to git), `os.environ.get()` reads from the OS or a `.env` file at runtime. The `.env` file is gitignored so secrets never reach the repo.

---

### `llm.py` — The LLM Provider Wrapper

A single function: `llm.generate(prompt, max_tokens=1024) -> str`.

All three standalone modules (`scheduler.py`, `outreach.py`, `job_scorer.py`) import this instead of talking to Gemini directly:

```python
# Every module calls this — not the Gemini SDK directly
import llm

text = llm.generate("Write a LinkedIn post about Python...", max_tokens=512)
```

**Why it exists:** it's the **single point of change** for the LLM provider. To switch from Gemini to any other model (Ollama, OpenAI, Mistral), you edit only `llm.py`. The three module files are completely unaffected.

**Key concept — provider abstraction:** the modules don't care *which* model generates the text, only that `generate(prompt)` returns a string. This is the same idea as a database driver — your app calls `db.query()`, the driver translates that to MySQL or PostgreSQL. `llm.py` is the driver.

**Under the hood:**
```python
from google import genai

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(max_output_tokens=max_tokens),
)
return response.text.strip()
```

Uses `gemini-2.5-flash` — Google's free-tier model that balances quality and speed for short text tasks like post generation and connection notes. Reads `GEMINI_API_KEY` from `.env`.

---

### `token_store.py` — Persisting OAuth Login State

Four functions:
- `save_tokens(tokens)` — writes `tokens.json`
- `load_tokens()` — reads `tokens.json`, returns `None` if missing
- `tokens_valid()` — returns `True` if access token is not expired
- `token_status()` — human-readable dict for the `linkedin_token_status` tool

**Why it exists:** OAuth access tokens expire (~60 days for LinkedIn). If we stored them only in memory, you would need to re-authenticate every time Claude Desktop restarted.

**Key concept — token expiry:** every OAuth token has an `expires_in` field (seconds from now). We store `expires_at = time.time() + expires_in` — an absolute Unix timestamp — so we can check `time.time() < expires_at` later without doing time arithmetic.

---

### `posts_store.py` — Local Post History

Three functions:
- `save_post(post)` — prepends a post record to `posts.json` (newest first)
- `load_posts(count)` — returns the most recent N posts
- `post_count()` — total posts saved

**Why it exists:** LinkedIn removed `r_member_social` scope from the free OAuth tier, so the official API cannot read posts back. Every post created via `create_text_post()` or `create_article_post()` is saved here as a fallback when Voyager credentials are not available.

**Key concept — write-ahead log pattern:** saving data locally at write time (when you know all the details) is a common pattern for systems that can't read back what they wrote. Databases use the same idea with WAL (Write-Ahead Log) for crash recovery.

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

**`get_valid_token()`** — called before every official API request. If the token expires within 5 minutes, it silently calls `refresh_access_token()`.

---

### `voyager.py` — The Unofficial Voyager API

LinkedIn's website and mobile app use an internal API called **Voyager** (`/voyager/api/...`). Unlike the official OAuth API, the Voyager endpoints expose reading posts and searching jobs without special permissions.

The `linkedin-api` package (by Tom Quirk) authenticates to Voyager by logging in with **username and password**, mimicking LinkedIn's Android app headers. Cookies are cached to `~/.linkedin_api/cookies/` after the first login, so subsequent calls are fast.

#### Key design decisions in `voyager.py`

**`_get_client()` with a module-level cache:**
```python
_client = None

def _get_client():
    global _client
    if _client is not None:
        return _client
    _client = Linkedin(email, password)
    return _client
```

The `global _client` pattern caches the `Linkedin` instance for the lifetime of the MCP server process. Creating a new `Linkedin` instance (which logs in) on every tool call would be slow and might trigger LinkedIn's bot detection.

**`get_my_posts(count)`:**
1. Calls `api.get_user_profile()` to get the logged-in user's `publicIdentifier` (their profile URL slug)
2. Calls `api.get_profile_posts(public_id=..., post_count=count)` which hits `/voyager/api/identity/profileUpdatesV2`
3. Parses the raw Voyager response to extract text, URN, engagement counts

**`search_jobs(keywords, ...)`:**
Calls `api.search_jobs(keywords=..., location_name=..., ...)` which hits the internal job search Voyager endpoint. Returns structured results (title, company, location, URL) instead of just a search URL.

**Rate limiting:** `linkedin-api` automatically sleeps `random.randint(2, 5)` seconds between requests to avoid triggering bot detection.

> **Note:** Voyager is not an official API. It may break if LinkedIn changes their internal endpoints. Use it responsibly.

---

### `linkedin_api.py` — The Router

This file acts as a **router** — it decides which backend to use for each operation and presents a single consistent interface to `server.py`.

```
create_text_post()    -> official OAuth API (POST /v2/ugcPosts)
                         + saves to posts_store

create_article_post() -> official OAuth API (POST /v2/ugcPosts)
                         + saves to posts_store

get_profile()         -> official OAuth API (GET /v2/userinfo)

get_my_posts()        -> voyager.get_my_posts()
                         fallback: posts_store.load_posts()

search_jobs()         -> voyager.search_jobs()
                         fallback: build_job_search_url()

build_job_search_url() -> pure URL construction, no API call
```

The fallback pattern in `get_my_posts` and `search_jobs`:
```python
try:
    import voyager
    return voyager.get_my_posts(count)
except RuntimeError as e:
    if "LINKEDIN_EMAIL" in str(e):
        # credentials not set — degrade gracefully
        return local_fallback()
    raise  # re-raise unexpected errors
```

This means the tool still works without Voyager credentials — it just returns less data.

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

### `scheduler.py` — Module 2: Automated Post Publishing

A **run-once** script: generates a LinkedIn post with Gemini and publishes it, then exits. No long-running process — the OS scheduler (Windows Task Scheduler or cron) calls it at the right time.

```python
# The entire entry point
if __name__ == "__main__":
    generate_and_publish()
```

**Why run-once instead of a long-running loop?** The `schedule` library keeps a Python process alive 24/7 just to wait. Task Scheduler already does that job at the OS level — it's more efficient, survives reboots, and runs whether or not any other Python process is running.

**Configuring:** `POST_TOPIC` in `.env` controls what Gemini writes about. Changing this is the only thing needed to shift the content strategy.

**Register with Windows Task Scheduler:**
```
schtasks /create /tn "LinkedIn Daily Post" /tr "\"path\to\.venv\Scripts\python.exe\" \"path\to\scheduler.py\"" /sc daily /st 09:00 /f
```

---

### `outreach.py` — Module 3: Connection Outreach

Searches LinkedIn for people matching `OUTREACH_KEYWORDS`, generates a personalised 300-character note for each via `llm.generate()`, then calls `api.add_connection(public_id, message=note)`.

**Rate limiting and deduplication:**
```python
# outreach_log.json tracks:
# - every person contacted (by public_id)
# - how many requests went out today
# - the date of last reset (resets daily)
```

The log file means the script is safe to run on a schedule — it will never contact the same person twice, and it stops at `OUTREACH_DAILY_LIMIT` (default 5) per calendar day.

**Note generation:** `llm.generate()` is called once per person with their name + headline. The result is truncated to 300 characters (LinkedIn's hard limit for connection notes).

**Uses Voyager**, not the official API — `api.add_connection()` from the `linkedin-api` package. This reuses the same authenticated Voyager session as post reading and job search.

---

### `job_scorer.py` — Module 4: Job Scoring

Fetches jobs via `linkedin_api.search_jobs()`, builds a profile context from the LinkedIn API + `profile.txt`, then asks Gemini to return a JSON array of scores.

**Used in two ways:**
1. As a library — imported by the `linkedin_score_jobs` MCP tool in `server.py`
2. As a CLI — `py -3 job_scorer.py --keywords "Python Engineer" --location "London"`

**Profile context priority:** LinkedIn profile (name, headline) is fetched via OAuth; `profile.txt` adds skills, experience, and preferences. Both are concatenated and passed to Gemini as the scoring baseline.

**Gemini JSON parsing:** Gemini sometimes wraps JSON in markdown code fences (` ```json ... ``` `). The parser strips these before calling `json.loads()`:
```python
clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
```
This is a common defensive pattern when asking any LLM to return structured data.

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
  |-> posts_store.save_post(result) -> write to posts.json
  v
return {"post_id": "...", "post_url": "https://www.linkedin.com/feed/update/..."}
  |
  v
Claude Desktop displays the post URL
```

---

## Data Flow: Reading Your Posts (Voyager)

```
Claude Desktop calls linkedin_get_my_posts(count=10)
  |
  v
server.py -> linkedin_api.get_my_posts(10)
  |
  v
linkedin_api: try voyager.get_my_posts(10)
  |
  v
voyager._get_client()
  |-> check if _client is cached
  |-> if not: Linkedin(email, password)
  |     -> POST https://www.linkedin.com/uas/authenticate  (mimics Android app)
  |     -> cache cookies to ~/.linkedin_api/cookies/
  |-> return cached _client
  |
  v
api.get_user_profile()  -> GET /voyager/api/me
  extract publicIdentifier (e.g. "buwaneka-halpage")
  |
  v
api.get_profile_posts(public_id="buwaneka-halpage", post_count=10)
  -> GET /voyager/api/identity/profileUpdatesV2?q=memberShareFeed&...
  -> sleeps 2-5s between paginated requests
  |
  v
parse each element: extract text, URN, likes, comments, shares
  |
  v
return {profile, returned, posts[]}
  |
  v
Claude Desktop displays posts with engagement stats
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
| `dict \| None` type hint | `token_store.py` | Union type — returns a dict or Nothing |
| `{**a, **b}` dict unpacking | `auth.py` | Merges two dicts; right-side keys win on conflict |
| `resp.raise_for_status()` | `linkedin_api.py` | Throws immediately on HTTP 4xx/5xx; prevents silent failures |
| `time.time()` | `token_store.py` | Unix timestamp (seconds since 1970); comparable across restarts |
| `global _client` + lazy init | `voyager.py`, `llm.py` | Module-level cache — creates expensive object once, reuses it |
| `try/except RuntimeError` | `linkedin_api.py` | Graceful degradation — falls back to simpler path if credentials missing |
| Provider abstraction | `llm.py` | Single wrapper around Gemini; swap providers by changing one file |
| `str.removeprefix/removesuffix` | `job_scorer.py` | Strip markdown fences from LLM JSON responses (Python 3.9+) |
| Run-once script pattern | `scheduler.py`, `outreach.py` | Script does its job and exits; OS scheduler handles timing |

---

## Common Extension Points

**Add a new LinkedIn API tool:**
1. Write a function in `linkedin_api.py` routing to the right backend (official API or voyager)
2. Add a `@mcp.tool()` wrapper in `server.py` with a clear docstring
3. Restart Claude Desktop — FastMCP registers it automatically

**Swap the LLM provider:**
Only `llm.py` needs to change. Replace the `google-genai` client with any other provider (Ollama, OpenAI, Mistral). The `generate(prompt, max_tokens)` signature stays the same — `scheduler.py`, `outreach.py`, and `job_scorer.py` are untouched.

**Swap the token storage backend:**
Only `token_store.py` needs to change. The four function signatures stay the same, but the implementation could use OS keychain, a database, or encrypted storage. Nothing else in the codebase changes.

**Add a new OAuth scope:**
1. Add the scope string to `SCOPES` in `config.py`
2. Enable the corresponding LinkedIn product in the Developer Portal
3. Delete `tokens.json` and re-run `linkedin_authenticate` — the user will consent to the new scope

**Add more Voyager features:**
`voyager.py` is the right place. The `linkedin-api` package also exposes: `get_feed_posts()`, `get_post_comments()`, `react_to_post()`, `send_message()`. Add a wrapper function in `voyager.py`, route it in `linkedin_api.py`, expose it as a tool in `server.py`.
