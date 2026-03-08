"""
LinkedIn MCP Server for Claude Desktop.

Tools exposed:
  - linkedin_authenticate        : Start OAuth 2.0 flow (run once)
  - linkedin_token_status        : Check if authenticated and token expiry
  - linkedin_get_profile         : Fetch your LinkedIn profile
  - linkedin_create_post         : Publish a text post
  - linkedin_create_article_post : Publish a post with article/URL preview
  - linkedin_get_my_posts        : Retrieve your own posts (Voyager API)
  - linkedin_search_jobs         : Search jobs with real results (Voyager API)
  - linkedin_job_search_url      : Build a job search URL (no credentials needed)
  - linkedin_score_jobs          : Search jobs and score each against your profile (Claude)

Run with:
  uv run server.py
"""

from mcp.server.fastmcp import FastMCP

import auth
import job_scorer
import linkedin_api
from token_store import token_status

mcp = FastMCP("LinkedIn")


# ---------------------------------------------------------------------------
# Authentication tools
# ---------------------------------------------------------------------------

@mcp.tool()
def linkedin_authenticate() -> str:
    """
    Start the LinkedIn OAuth 2.0 authorization flow.

    Opens a browser window for you to log in and approve access.
    After approval LinkedIn redirects back to localhost and the token
    is saved automatically. You only need to run this once — tokens
    are refreshed automatically thereafter.

    Required scopes: openid, profile, email, w_member_social
    """
    try:
        tokens = auth.run_oauth_flow()
        # Eagerly cache the person URN
        try:
            profile = linkedin_api.get_profile()
            name = profile.get("name", "")
            return (
                f"Authenticated successfully as {name}. "
                f"Token valid for ~{int(tokens['expires_in'] // 3600)} hours. "
                "You can now use all LinkedIn tools."
            )
        except Exception:
            return "Authenticated successfully. Token saved."
    except TimeoutError:
        return "Authentication timed out — the browser window was not completed within 2 minutes. Try again."
    except Exception as e:
        return f"Authentication failed: {e}"


@mcp.tool()
def linkedin_token_status() -> dict:
    """
    Check whether you are authenticated with LinkedIn and when the token expires.

    Returns a dict with:
      - authenticated (bool)
      - expires_in (str)  — e.g. "1h 45m"
      - person_urn (str)  — your LinkedIn member URN
    """
    return token_status()


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@mcp.tool()
def linkedin_get_profile() -> dict:
    """
    Fetch your LinkedIn profile information.

    Returns name, email, profile picture URL, and your person URN.
    Also caches the person URN for use in post creation.
    """
    try:
        return linkedin_api.get_profile()
    except Exception as e:
        return {"error": str(e), "hint": "Make sure you have run linkedin_authenticate first."}


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

@mcp.tool()
def linkedin_create_post(text: str, visibility: str = "PUBLIC") -> dict:
    """
    Publish a text post to your LinkedIn feed.

    Args:
        text:       The post body. Supports line breaks. Max ~3000 chars recommended.
        visibility: Who can see the post. "PUBLIC" (default) or "CONNECTIONS".

    Returns:
        post_id and post_url of the newly created post.

    Example:
        linkedin_create_post("Excited to share my latest project! #buildinpublic")
    """
    if not text or not text.strip():
        return {"error": "Post text cannot be empty."}
    if visibility not in ("PUBLIC", "CONNECTIONS"):
        return {"error": "visibility must be 'PUBLIC' or 'CONNECTIONS'."}
    try:
        return linkedin_api.create_text_post(text.strip(), visibility)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def linkedin_create_article_post(
    text: str,
    url: str,
    title: str,
    description: str = "",
    visibility: str = "PUBLIC",
) -> dict:
    """
    Publish a LinkedIn post that includes an article or URL link preview card.

    Args:
        text:        Your commentary above the link preview (required).
        url:         The URL of the article or resource to share (required).
        title:       Title shown in the link preview card (required).
        description: Optional subtitle shown in the link preview card.
        visibility:  "PUBLIC" (default) or "CONNECTIONS".

    Returns:
        post_id, post_url, and the shared_url.

    Example:
        linkedin_create_article_post(
            text="Great read on AI in 2025:",
            url="https://example.com/ai-article",
            title="The State of AI",
            description="A deep dive into where AI is headed."
        )
    """
    if not text or not url or not title:
        return {"error": "text, url, and title are all required."}
    try:
        return linkedin_api.create_article_post(
            text=text.strip(),
            url=url.strip(),
            title=title.strip(),
            description=description.strip(),
            visibility=visibility,
        )
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# My posts
# ---------------------------------------------------------------------------

@mcp.tool()
def linkedin_get_my_posts(count: int = 10) -> dict:
    """
    Retrieve your own LinkedIn posts with engagement stats (likes, comments, shares).

    Uses LinkedIn's Voyager API (requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env).
    Falls back to the local post history (posts.json) if credentials are not set.

    Args:
        count: How many posts to return (1–100, default 10).

    Returns:
        profile    — your LinkedIn public ID
        returned   — number of posts in this response
        posts[]    — list of posts, each with:
                       urn, post_url, text (first 500 chars),
                       age (e.g. "2 mo"), likes, comments, shares
    """
    try:
        return linkedin_api.get_my_posts(count)
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------

@mcp.tool()
def linkedin_search_jobs(
    keywords: str,
    location: str = "",
    remote: bool = False,
    job_type: str = "",
    experience: str = "",
    count: int = 10,
) -> dict:
    """
    Search LinkedIn jobs and return structured results — titles, companies, locations, and links.

    Uses LinkedIn's Voyager API (requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env).
    Falls back to a filtered search URL if credentials are not set.

    Args:
        keywords:   Role title or skills, e.g. "Senior Python Engineer AI".
        location:   City or country, e.g. "London, United Kingdom". Leave blank for worldwide.
        remote:     True to filter for remote-only roles.
        job_type:   One of: FULL_TIME, PART_TIME, CONTRACT, TEMPORARY, INTERNSHIP.
        experience: Seniority level: "1" internship, "2" entry, "3" associate,
                    "4" mid-senior, "5" director, "6" executive.
        count:      Number of results to return (1–50, default 10).

    Returns:
        keywords, location, returned, jobs[] — each with job_id, title,
        company, location, job_url, applies count.
    """
    if not keywords:
        return {"error": "keywords is required."}
    try:
        return linkedin_api.search_jobs(
            keywords=keywords,
            location=location,
            remote=remote,
            job_type=job_type,
            experience=experience,
            count=count,
        )
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def linkedin_job_search_url(
    keywords: str,
    location: str = "",
    remote: bool = False,
    job_type: str = "",
    date_posted: str = "",
) -> dict:
    """
    Build a LinkedIn job search URL with your filters applied.

    Because LinkedIn does not expose a job search API to consumer apps,
    this tool generates the correct filtered URL. Open it in your browser,
    then paste interesting job descriptions back here for Claude to analyse —
    matching skills, summarising requirements, drafting applications, etc.

    Args:
        keywords:    Role title or skills, e.g. "Senior Python Engineer AI".
        location:    City or country, e.g. "London, UK" or "United States".
                     Leave blank for worldwide.
        remote:      True to filter for remote-only roles.
        job_type:    One of: FULL_TIME, PART_TIME, CONTRACT, INTERNSHIP, TEMPORARY.
                     Leave blank for all types.
        date_posted: How recent: "r86400" (24 h), "r604800" (1 week),
                     "r2592000" (1 month). Leave blank for all time.

    Returns:
        search_url and a summary of applied filters.
    """
    if not keywords:
        return {"error": "keywords is required."}
    return linkedin_api.build_job_search_url(
        keywords=keywords,
        location=location,
        remote=remote,
        job_type=job_type,
        date_posted=date_posted,
    )


@mcp.tool()
def linkedin_score_jobs(
    keywords: str,
    location: str = "",
    remote: bool = False,
    job_type: str = "",
    experience: str = "",
    count: int = 10,
) -> dict:
    """
    Search LinkedIn jobs and score each one against your profile using Claude.

    Combines your LinkedIn profile with profile.txt (if present) to build
    a scoring context, then asks Claude to rate each job 1–10 with a fit
    summary and skill gap notes. Results are sorted best-first.

    Requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD (Voyager) and ANTHROPIC_API_KEY.
    Add your CV / skills to profile.txt in the project root for richer scoring.

    Args:
        keywords:   Role title or skills, e.g. "Senior Python Engineer AI".
        location:   City or country. Leave blank for worldwide.
        remote:     True to filter for remote-only roles.
        job_type:   One of: FULL_TIME, PART_TIME, CONTRACT, TEMPORARY, INTERNSHIP.
        experience: "1" internship, "2" entry, "3" associate,
                    "4" mid-senior, "5" director, "6" executive.
        count:      Number of jobs to fetch and score (1–50, default 10).

    Returns:
        keywords, location, returned, scored (bool), jobs[] — each with
        job_id, title, company, location, job_url, applies,
        score (1–10), fit (sentence), gaps (string).
    """
    if not keywords:
        return {"error": "keywords is required."}
    try:
        return job_scorer.score_jobs(
            keywords=keywords,
            location=location,
            remote=remote,
            job_type=job_type,
            experience=experience,
            count=count,
        )
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()  # stdio transport — required by Claude Desktop
