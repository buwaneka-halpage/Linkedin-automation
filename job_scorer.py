"""
Module 4: Job search with Gemini scoring.

Searches LinkedIn jobs via the Voyager API, combines your LinkedIn profile
with an optional profile.txt file, then asks Gemini to score each job 1–10
with a fit summary and skill gap notes.

Used directly by the linkedin_score_jobs MCP tool in server.py.
Can also be run standalone:
  py -3 job_scorer.py --keywords "Python Engineer" --location "London" --count 10
"""

import json
import logging
import os

import llm
from dotenv import load_dotenv

import linkedin_api

load_dotenv()

PROFILE_FILE = os.path.join(os.path.dirname(__file__), "profile.txt")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _load_profile_txt() -> str:
    """Read profile.txt if it exists; return empty string otherwise."""
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _build_profile_context() -> str:
    """Combine LinkedIn profile API data with profile.txt."""
    lines = []

    try:
        li = linkedin_api.get_profile()
        if li.get("name"):
            lines.append(f"Name: {li['name']}")
        if li.get("headline"):
            lines.append(f"Headline: {li['headline']}")
        if li.get("email"):
            lines.append(f"Email: {li['email']}")
    except Exception:
        pass  # Tokens may not be configured; profile.txt will carry the context

    extra = _load_profile_txt()
    if extra:
        if lines:
            lines.append("")
        lines.append("--- CV / Skills ---")
        lines.append(extra)

    return "\n".join(lines) if lines else "(no profile context available — add profile.txt)"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_jobs(jobs: list[dict], profile_context: str) -> list[dict]:
    """
    Send jobs + profile to Gemini; return the same job list with
    score, fit, and gaps fields added and sorted best-first.
    """
    jobs_text = "\n\n".join(
        f"Job {i + 1}: {j.get('title', 'Unknown')} at {j.get('company', 'Unknown')}\n"
        f"Location: {j.get('location', '')}\n"
        f"URL: {j.get('job_url', '')}"
        for i, j in enumerate(jobs)
    )

    raw = llm.generate(
        "Score these LinkedIn job listings against the candidate profile.\n\n"
        f"CANDIDATE PROFILE:\n{profile_context}\n\n"
        f"JOBS:\n{jobs_text}\n\n"
        "For each job return:\n"
        "  score  — integer 1–10 (10 = perfect fit)\n"
        "  fit    — one sentence on why it is a good or poor fit\n"
        "  gaps   — skills or experience the candidate is missing (empty string if none)\n\n"
        "Return a JSON array only, no other text:\n"
        '[{"job_index": 1, "score": 8, "fit": "...", "gaps": "..."}]',
        max_tokens=2048,
    )

    # Gemini sometimes wraps JSON in markdown code fences — strip them
    clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        scores = json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        log.warning("Gemini returned non-JSON scoring response; jobs returned unscored.")
        return jobs

    score_map = {s["job_index"]: s for s in scores if isinstance(s, dict)}
    for i, job in enumerate(jobs):
        entry = score_map.get(i + 1, {})
        job["score"] = entry.get("score", 0)
        job["fit"] = entry.get("fit", "")
        job["gaps"] = entry.get("gaps", "")

    jobs.sort(key=lambda j: j.get("score", 0), reverse=True)
    return jobs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_jobs(
    keywords: str,
    location: str = "",
    remote: bool = False,
    job_type: str = "",
    experience: str = "",
    count: int = 10,
) -> dict:
    """
    Search LinkedIn jobs and score each one against your profile with Claude.

    Returns the same structure as linkedin_api.search_jobs(), with three
    extra fields per job: score (1–10), fit (one sentence), gaps (string).
    Jobs are sorted best-first by score.
    """
    result = linkedin_api.search_jobs(
        keywords=keywords,
        location=location,
        remote=remote,
        job_type=job_type,
        experience=experience,
        count=count,
    )

    if "error" in result or not result.get("jobs"):
        return result

    profile_context = _build_profile_context()
    result["jobs"] = _score_jobs(result["jobs"], profile_context)
    result["scored"] = True
    result["profile_used"] = bool(profile_context.strip())

    return result


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Score LinkedIn jobs against your profile.")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    output = score_jobs(
        keywords=args.keywords,
        location=args.location,
        remote=args.remote,
        count=args.count,
    )

    for job in output.get("jobs", []):
        print(f"[{job.get('score', '?')}/10] {job.get('title')} @ {job.get('company')}")
        print(f"  Fit:  {job.get('fit')}")
        if job.get("gaps"):
            print(f"  Gaps: {job.get('gaps')}")
        print(f"  URL:  {job.get('job_url')}")
        print()
