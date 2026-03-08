"""
LinkedIn Voyager API client (unofficial).

Uses the linkedin-api package which authenticates via username/password
and hits LinkedIn's internal Voyager endpoints (same as the mobile app).

This is NOT part of LinkedIn's official API. Use at your own risk.
Credentials are loaded from LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env.
"""

import os
from dotenv import load_dotenv

load_dotenv()

_client = None  # cached Linkedin instance


def _get_client():
    """Return a cached linkedin-api client, creating one if needed."""
    global _client
    if _client is not None:
        return _client

    from linkedin_api import Linkedin

    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")

    if not email or not password:
        raise RuntimeError(
            "LINKEDIN_EMAIL and LINKEDIN_PASSWORD must be set in .env "
            "to use post reading and job search features."
        )

    _client = Linkedin(email, password)
    return _client


def get_my_posts(count: int = 10) -> dict:
    """
    Fetch the authenticated user's own LinkedIn posts via Voyager API.

    Args:
        count: Number of posts to return (1-100).
    """
    api = _get_client()

    # Get the logged-in user's profile to retrieve their public_id
    me = api.get_user_profile()
    public_id = (
        me.get("miniProfile", {}).get("publicIdentifier")
        or me.get("publicIdentifier", "")
    )

    if not public_id:
        return {"error": "Could not determine your LinkedIn profile public ID."}

    raw_posts = api.get_profile_posts(public_id=public_id, post_count=min(count, 100))

    posts = []
    for item in raw_posts:
        # Extract post text
        commentary = item.get("commentary") or {}
        text = commentary.get("text", {}).get("text", "") if isinstance(commentary.get("text"), dict) else ""

        # Fallback: try nested value path
        if not text:
            text = (
                item.get("value", {})
                .get("com.linkedin.voyager.feed.render.UpdateV2", {})
                .get("commentary", {})
                .get("text", {})
                .get("text", "")
            )

        # Extract post URN and URL
        urn = item.get("updateMetadata", {}).get("urn", "")
        post_url = f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""

        # Extract age string (e.g. "2 mo", "1 wk")
        age = (
            item.get("actor", {})
            .get("subDescription", {})
            .get("text", "")
        )

        # Extract engagement counts
        social = item.get("socialDetail", {}).get("totalSocialActivityCounts", {})
        likes    = social.get("numLikes", 0)
        comments = social.get("numComments", 0)
        shares   = social.get("numShares", 0)

        posts.append({
            "urn":      urn,
            "post_url": post_url,
            "text":     text[:500] + ("..." if len(text) > 500 else ""),
            "age":      age,
            "likes":    likes,
            "comments": comments,
            "shares":   shares,
        })

    return {
        "profile":  public_id,
        "returned": len(posts),
        "posts":    posts,
    }


def search_jobs(
    keywords: str,
    location: str = "",
    remote: bool = False,
    job_type: str = "",
    experience: str = "",
    count: int = 10,
) -> dict:
    """
    Search LinkedIn jobs via the Voyager API and return structured results.

    Args:
        keywords:   Job title or skills, e.g. "Senior Python Engineer".
        location:   City or country, e.g. "London, United Kingdom".
        remote:     True to filter for remote-only roles.
        job_type:   "FULL_TIME", "PART_TIME", "CONTRACT", "TEMPORARY", "INTERNSHIP".
        experience: "1" (internship), "2" (entry), "3" (associate),
                    "4" (mid-senior), "5" (director), "6" (executive).
        count:      Number of results to return (1-50).
    """
    api = _get_client()

    kwargs = {
        "keywords": keywords,
        "limit": min(count, 50),
    }

    if location:
        kwargs["location_name"] = location

    if remote:
        kwargs["remote"] = ["2"]  # LinkedIn remote filter code

    # Map job type string to linkedin-api code
    if job_type:
        type_map = {
            "FULL_TIME":  "F",
            "PART_TIME":  "P",
            "CONTRACT":   "C",
            "TEMPORARY":  "T",
            "INTERNSHIP": "I",
        }
        code = type_map.get(job_type.upper())
        if code:
            kwargs["job_type"] = [code]

    if experience:
        kwargs["experience"] = [experience]

    raw_jobs = api.search_jobs(**kwargs)

    jobs = []
    for job in raw_jobs:
        entity = job.get("entityUrn", "")
        job_id = entity.split(":")[-1] if entity else ""

        # Title + company from dashEntityUrn or direct fields
        title   = job.get("title", "")
        company = job.get("companyDetails", {}).get(
            "com.linkedin.voyager.deco.jobs.web.shared.WebCompactJobPostingCompany", {}
        ).get("companyResolutionResult", {}).get("name", "")

        # Fallback for company name
        if not company:
            company = job.get("formattedLocation", "")

        location_str = job.get("formattedLocation", "")
        listed_at    = job.get("listedAt", 0)
        applies      = job.get("applies", 0)

        job_url = f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else ""

        jobs.append({
            "job_id":    job_id,
            "title":     title,
            "company":   company,
            "location":  location_str,
            "job_url":   job_url,
            "applies":   applies,
        })

    return {
        "keywords": keywords,
        "location": location or "Worldwide",
        "returned": len(jobs),
        "jobs":     jobs,
    }
