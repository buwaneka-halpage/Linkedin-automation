# LinkedIn Automation — MCP Server for Claude Desktop

A Python MCP (Model Context Protocol) server that connects Claude Desktop to LinkedIn via OAuth 2.0 and the Voyager API. Lets you generate posts, share articles, retrieve feed history, research and score jobs, and run automated outreach — all from natural language in Claude.

---

## MCP Tools (Claude Desktop)

| Tool | What it does |
|------|-------------|
| `linkedin_authenticate` | One-time OAuth 2.0 browser login |
| `linkedin_token_status` | Check auth state + token expiry |
| `linkedin_get_profile` | Fetch your name, email, URN |
| `linkedin_create_post` | Publish a text post |
| `linkedin_create_article_post` | Share a URL with a link preview card |
| `linkedin_get_my_posts` | Retrieve your posts with likes, comments, shares |
| `linkedin_search_jobs` | Search jobs — real results via Voyager API |
| `linkedin_job_search_url` | Build a filtered job search URL (no Voyager credentials needed) |
| `linkedin_score_jobs` | Search jobs and score each one against your profile using Gemini |

---

## Standalone Modules

| Script | Module | What it does | How to run |
|--------|--------|-------------|------------|
| `scheduler.py` | 2 | Generates a post with Gemini and publishes it | Task Scheduler / cron |
| `outreach.py` | 3 | Sends personalised connection requests (rate-limited 5/day) | Task Scheduler / cron |
| `job_scorer.py` | 4 | Scores jobs from CLI (same logic as `linkedin_score_jobs` tool) | `py -3 job_scorer.py --keywords "..."` |

---

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- A [LinkedIn Developer App](https://developer.linkedin.com) with:
  - `Sign in with LinkedIn using OpenID Connect` product added
  - `Share on LinkedIn` product added
  - Redirect URI: `http://localhost:8080/callback`
- Claude Desktop
- A free [Gemini API key](https://aistudio.google.com/apikey) (for Modules 2, 3, 4)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/buwaneka-halpage/Linkedin-automation.git
cd Linkedin-automation
uv sync
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```env
# LinkedIn Developer App — required for posting and profile
LINKEDIN_CLIENT_ID=your_client_id_here
LINKEDIN_CLIENT_SECRET=your_client_secret_here
LINKEDIN_REDIRECT_PORT=8080

# Your LinkedIn account — required for reading posts, job search, outreach
LINKEDIN_EMAIL=your_linkedin_email@example.com
LINKEDIN_PASSWORD=your_linkedin_password

# Gemini — required for Modules 2, 3, 4
# Free key at https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Module 2: what Gemini should write about
POST_TOPIC=share a professional insight about software engineering or career growth

# Module 3: who to target for connection outreach
OUTREACH_KEYWORDS=Python engineer
OUTREACH_YOUR_ROLE=software engineer
OUTREACH_REASON=explore collaboration opportunities
```

### 3. (Optional) Add your CV for job scoring

Copy the template and fill it in:

```bash
cp profile.example.txt profile.txt
```

`profile.txt` is read by `linkedin_score_jobs` and `job_scorer.py` to score jobs against your actual skills and preferences.

### 4. Register with Claude Desktop

Add the following to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "C:\\path\\to\\Linkedin-automation\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Linkedin-automation\\server.py"]
    }
  }
}
```

Replace the paths with your actual install location.

### 5. Restart Claude Desktop

Fully quit (system tray → Quit) and reopen. A tools icon will appear in the chat input.

---

## Authentication

**OAuth 2.0** (for posting) — run once in Claude Desktop:

> "Run linkedin_authenticate"

A browser window opens → log in to LinkedIn → approve → done.
Tokens are saved to `tokens.json` and auto-refresh (valid ~60 days).

**Voyager API** (for reading posts, job search, outreach) — no extra step needed. `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` in `.env` are used automatically. Cookies are cached on first use.

---

## Usage

### Claude Desktop

**Publish a post:**
> "Create a LinkedIn post about my new Python project launching today"

**Share an article:**
> "Share this article on LinkedIn with a short commentary: https://example.com/article"

**See recent posts with engagement:**
> "Show me my last 10 LinkedIn posts with likes and comments"

**Search jobs:**
> "Search LinkedIn for Senior Python Engineer roles in London, remote only"

**Score jobs against my profile:**
> "Find 10 Python backend roles in Europe and score them against my profile"

### Standalone scripts

**Publish one post now (Module 2):**
```bash
py -3 scheduler.py
```

**Run connection outreach (Module 3):**
```bash
py -3 outreach.py
```

**Score jobs from command line (Module 4):**
```bash
py -3 job_scorer.py --keywords "Python Engineer" --location "London" --count 10
```

### Scheduling with Windows Task Scheduler

Register `scheduler.py` to run daily at 9am (run once to register):

```
schtasks /create /tn "LinkedIn Daily Post" /tr "\"C:\path\to\.venv\Scripts\python.exe\" \"C:\path\to\scheduler.py\"" /sc daily /st 09:00 /f
```

Same pattern for `outreach.py`. To remove a task:

```
schtasks /delete /tn "LinkedIn Daily Post" /f
```

---

## Project Structure

```
├── server.py            # FastMCP server — 9 MCP tool definitions
├── auth.py              # OAuth 2.0 three-legged flow + token refresh
├── linkedin_api.py      # LinkedIn REST API wrappers (official + Voyager router)
├── voyager.py           # Unofficial Voyager API (post reading, job search, outreach)
├── posts_store.py       # Local post history fallback (posts.json)
├── token_store.py       # Persist/load OAuth tokens (tokens.json)
├── config.py            # Loads .env, constants
├── llm.py               # Thin Gemini wrapper — all LLM calls go through here
├── scheduler.py         # Module 2: generate + publish one post, run via Task Scheduler
├── outreach.py          # Module 3: personalised connection requests, rate-limited 5/day
├── job_scorer.py        # Module 4: job search + Gemini scoring, also used by MCP tool
├── profile.example.txt  # CV template for job scoring context
├── pyproject.toml       # Dependencies
├── .env.example         # Credential template
└── .gitignore           # Excludes .env, tokens.json, posts.json, outreach_log.json, profile.txt
```

---

## Two Authentication Tracks

| Track | Credentials | Used for |
|-------|------------|---------|
| **OAuth 2.0** | Client ID + Secret (Developer App) | Creating posts, fetching profile |
| **Voyager API** | Email + Password (your account) | Reading posts, searching jobs, outreach |

LinkedIn removed `r_member_social` (read posts) from the free OAuth tier, which is why two separate auth methods are needed.

---

## OAuth Scopes

| Scope | Purpose |
|-------|---------|
| `openid` | OpenID Connect identity |
| `profile` | Name, headline, photo |
| `email` | Primary email address |
| `w_member_social` | Post, comment, like on your behalf |

---

## Security Notes

- `tokens.json`, `posts.json`, `outreach_log.json`, `profile.txt` are all gitignored
- `.env` is gitignored — never commit it
- The Voyager API uses your LinkedIn credentials — keep `.env` private
- The OAuth callback server only listens on `localhost`
- `outreach.py` is rate-limited to 5 requests/day by default; raising this risks account flags

---

## Troubleshooting

**Tools not showing in Claude Desktop**
- Fully quit Claude Desktop (system tray → Quit), not just close the window
- Check `%APPDATA%\Claude\claude_desktop_config.json` still contains the `mcpServers` block
- Claude Desktop may overwrite the config when you change preferences — re-add if needed

**`linkedin_get_my_posts` returns empty or local store only**
Add `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` to `.env`, then restart Claude Desktop.

**Voyager login fails or raises ChallengeException**
LinkedIn flagged the login as suspicious. Log in normally in your browser, complete any security check, then retry.

**OAuth timeout**
The browser flow has a 5-minute window. If it times out, the auth URL is printed to the console — open it manually in a browser.

**`GEMINI_API_KEY` not set error**
Add `GEMINI_API_KEY=...` to `.env`. Free key at https://aistudio.google.com/apikey

---

## License

MIT
