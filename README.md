# LinkedIn Automation — MCP Server for Claude Desktop

A Python MCP (Model Context Protocol) server that connects Claude Desktop to LinkedIn via OAuth 2.0. Lets you generate posts, share articles, retrieve your feed history, and research jobs — all from natural language in Claude.

---

## Features

| Tool | What it does |
|------|-------------|
| `linkedin_authenticate` | One-time OAuth 2.0 browser login |
| `linkedin_token_status` | Check auth state + token expiry |
| `linkedin_get_profile` | Fetch your name, email, URN |
| `linkedin_create_post` | Publish a text post |
| `linkedin_create_article_post` | Share a URL with a link preview card |
| `linkedin_get_my_posts` | Retrieve your recent posts |
| `linkedin_job_search_url` | Build filtered job search URLs |

---

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- A [LinkedIn Developer App](https://developer.linkedin.com) with:
  - `Sign in with LinkedIn using OpenID Connect` product added
  - `Share on LinkedIn` product added
  - Redirect URI: `http://localhost:8080/callback`
- Claude Desktop

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
LINKEDIN_CLIENT_ID=your_client_id_here
LINKEDIN_CLIENT_SECRET=your_client_secret_here
LINKEDIN_REDIRECT_PORT=8080
```

### 3. Register with Claude Desktop

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

### 4. Restart Claude Desktop

Fully quit (system tray → Quit) and reopen. A tools icon will appear in the chat input.

---

## Authentication

Run once in Claude Desktop:

> "Run linkedin_authenticate"

A browser window opens → log in to LinkedIn → approve → done.
Tokens are saved to `tokens.json` and auto-refresh (valid ~60 days).

---

## Usage Examples

**Publish a post:**
> "Create a LinkedIn post about my new Python project launching today"

**Share an article:**
> "Share this article on LinkedIn with a short commentary: https://example.com/article"

**See your recent posts:**
> "Show me my last 5 LinkedIn posts"

**Research jobs:**
> "Build a job search URL for Senior Python Engineer roles in London, remote only"

---

## Project Structure

```
├── server.py          # FastMCP server — tool definitions
├── auth.py            # OAuth 2.0 three-legged flow + token refresh
├── linkedin_api.py    # LinkedIn REST API wrappers
├── token_store.py     # Persist/load tokens from tokens.json
├── config.py          # Loads .env, constants
├── pyproject.toml     # Dependencies (mcp, httpx, python-dotenv)
├── .env.example       # Credential template
└── .gitignore         # Excludes .env and tokens.json
```

---

## OAuth Scopes

| Scope | Purpose |
|-------|---------|
| `openid` | OpenID Connect identity |
| `profile` | Name, headline, photo |
| `email` | Primary email address |
| `w_member_social` | Post, comment, like + read own posts |

---

## Security Notes

- `tokens.json` is gitignored — never commit it
- `.env` is gitignored — never commit it
- Tokens are stored in plain JSON locally; restrict file permissions if on a shared machine
- The OAuth callback server only listens on `localhost`

---

## Troubleshooting

**Tools not showing in Claude Desktop**
- Fully quit Claude Desktop (system tray → Quit), not just close the window
- Check `%APPDATA%\Claude\claude_desktop_config.json` still contains the `mcpServers` block
- Claude Desktop may overwrite the config when you change preferences — re-add the block if needed

**`r_member_social` scope error on `linkedin_get_my_posts`**
Add the `Share on LinkedIn` product to your LinkedIn Developer App, then re-run `linkedin_authenticate`.

**OAuth timeout**
The browser flow has a 5-minute window. If it times out, the auth URL is printed to the console — open it manually in a browser.

---

## License

MIT
