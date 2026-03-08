"""
LinkedIn REST API wrappers.

All functions obtain a valid token automatically via auth.get_valid_token().
"""

import time

import httpx

import config
from auth import get_valid_token
from token_store import load_tokens, save_tokens


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_valid_token()}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def get_profile() -> dict:
    """
    Fetch the authenticated member's profile via OpenID Connect userinfo.
    Also caches the person URN into tokens.json for post authoring.
    """
    resp = httpx.get(
        f"{config.API_BASE}/v2/userinfo",
        headers=_headers(),
    )
    resp.raise_for_status()
    data = resp.json()

    # LinkedIn's userinfo sub is the member ID — build the URN
    person_id = data.get("sub", "")
    person_urn = f"urn:li:person:{person_id}"

    # Cache urn into tokens file so posts don't need a separate call
    tokens = load_tokens() or {}
    if tokens.get("person_urn") != person_urn:
        tokens["person_urn"] = person_urn
        save_tokens(tokens)

    return {
        "name": data.get("name", ""),
        "given_name": data.get("given_name", ""),
        "family_name": data.get("family_name", ""),
        "email": data.get("email", ""),
        "picture": data.get("picture", ""),
        "person_urn": person_urn,
        "locale": data.get("locale", ""),
    }


def _get_person_urn() -> str:
    """Return cached person URN, fetching profile if not yet cached."""
    tokens = load_tokens() or {}
    if tokens.get("person_urn"):
        return tokens["person_urn"]
    profile = get_profile()
    return profile["person_urn"]


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

def create_text_post(text: str, visibility: str = "PUBLIC") -> dict:
    """
    Create a plain-text share on LinkedIn.

    Args:
        text:       Post body (max ~3000 chars recommended).
        visibility: "PUBLIC" or "CONNECTIONS".

    Returns:
        dict with post_id and post_url.
    """
    author = _get_person_urn()
    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        },
    }

    resp = httpx.post(
        f"{config.API_BASE}/v2/ugcPosts",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()

    post_id = resp.headers.get("x-restli-id", "")
    return {
        "post_id": post_id,
        "post_url": f"https://www.linkedin.com/feed/update/{post_id}/",
        "visibility": visibility,
    }


def create_article_post(
    text: str,
    url: str,
    title: str,
    description: str = "",
    visibility: str = "PUBLIC",
) -> dict:
    """
    Create a LinkedIn post that shares an article/URL with a link preview.

    Args:
        text:        Commentary text above the link preview.
        url:         URL of the article to share.
        title:       Title shown in the link preview card.
        description: Optional subtitle in the link preview card.
        visibility:  "PUBLIC" or "CONNECTIONS".
    """
    author = _get_person_urn()
    media = {
        "status": "READY",
        "description": {"text": description},
        "originalUrl": url,
        "title": {"text": title},
    }
    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "ARTICLE",
                "media": [media],
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        },
    }

    resp = httpx.post(
        f"{config.API_BASE}/v2/ugcPosts",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()

    post_id = resp.headers.get("x-restli-id", "")
    return {
        "post_id": post_id,
        "post_url": f"https://www.linkedin.com/feed/update/{post_id}/",
        "visibility": visibility,
        "shared_url": url,
    }


# ---------------------------------------------------------------------------
# Fetch own posts
# ---------------------------------------------------------------------------

def get_my_posts(count: int = 10) -> dict:
    """
    Retrieve the authenticated member's own UGC posts.

    Uses GET /v2/ugcPosts?q=authors with the cached person URN.
    Requires r_member_social scope. If missing, returns a clear error
    with instructions to add the scope to the LinkedIn app.

    Args:
        count: Number of posts to return (1–50).
    """
    author = _get_person_urn()
    params = {
        "q": "authors",
        "authors": f"List({author})",
        "count": min(max(count, 1), 50),
        "sortBy": "LAST_MODIFIED",
    }

    resp = httpx.get(
        f"{config.API_BASE}/v2/ugcPosts",
        headers=_headers(),
        params=params,
    )

    if resp.status_code == 403:
        return {
            "error": "Missing r_member_social scope.",
            "fix": (
                "Go to developer.linkedin.com → your app → Products → "
                "add 'Share on LinkedIn' (which includes r_member_social), "
                "then re-run linkedin_authenticate."
            ),
        }

    resp.raise_for_status()
    data = resp.json()

    posts = []
    for item in data.get("elements", []):
        content = item.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
        text = content.get("shareCommentary", {}).get("text", "")
        media_category = content.get("shareMediaCategory", "NONE")

        # Extract article URL if present
        article_url = ""
        media = content.get("media", [])
        if media:
            article_url = media[0].get("originalUrl", "")

        post_id = item.get("id", "")
        created_ms = item.get("created", {}).get("time", 0)
        created_iso = ""
        if created_ms:
            import datetime
            created_iso = datetime.datetime.utcfromtimestamp(created_ms / 1000).strftime("%Y-%m-%d %H:%M UTC")

        posts.append({
            "post_id": post_id,
            "post_url": f"https://www.linkedin.com/feed/update/{post_id}/",
            "text": text[:300] + ("..." if len(text) > 300 else ""),
            "type": media_category,
            "article_url": article_url,
            "created": created_iso,
            "visibility": item.get("visibility", {}).get("com.linkedin.ugc.MemberNetworkVisibility", ""),
            "state": item.get("lifecycleState", ""),
        })

    return {
        "total": data.get("paging", {}).get("total", len(posts)),
        "returned": len(posts),
        "posts": posts,
    }


# ---------------------------------------------------------------------------
# Job research (search URL builder — consumer API has no job search endpoint)
# ---------------------------------------------------------------------------

def build_job_search_url(
    keywords: str,
    location: str = "",
    remote: bool = False,
    job_type: str = "",
    date_posted: str = "",
) -> dict:
    """
    Build a LinkedIn job search URL with filters.

    LinkedIn does not expose a public Job Search API in the consumer tier.
    This returns a pre-filtered URL for the user to open, plus structured
    search parameters Claude can reason over.

    Args:
        keywords:    Job title or skills (e.g. "Senior Python Engineer").
        location:    City, country, or "Worldwide" (e.g. "London, UK").
        remote:      Include only remote roles.
        job_type:    "FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY".
        date_posted: "r86400" (24h), "r604800" (week), "r2592000" (month).
    """
    from urllib.parse import urlencode, quote_plus

    base = "https://www.linkedin.com/jobs/search/"
    params: dict = {"keywords": keywords}

    if location:
        params["location"] = location
    if remote:
        params["f_WT"] = "2"  # LinkedIn remote filter
    if job_type:
        type_map = {
            "FULL_TIME": "F",
            "PART_TIME": "P",
            "CONTRACT": "C",
            "TEMPORARY": "T",
            "INTERNSHIP": "I",
        }
        params["f_JT"] = type_map.get(job_type.upper(), "")
    if date_posted:
        params["f_TPR"] = date_posted

    search_url = f"{base}?{urlencode(params)}"

    return {
        "search_url": search_url,
        "keywords": keywords,
        "location": location or "Any",
        "remote_only": remote,
        "job_type": job_type or "Any",
        "date_posted_filter": date_posted or "Any time",
        "note": (
            "LinkedIn's consumer API does not provide a job search endpoint. "
            "Open the URL above in your browser to view results. "
            "Paste job descriptions back into Claude for analysis."
        ),
    }
