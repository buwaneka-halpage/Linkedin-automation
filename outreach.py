"""
Module 3: Automated LinkedIn connection outreach.

Searches for professionals matching configured criteria, generates a
personalised connection note via Gemini, then sends the request via the
Voyager API (linkedin-api package). Rate-limited to OUTREACH_DAILY_LIMIT
requests per day (default: 5) to avoid triggering LinkedIn's bot detection.

Sent requests are logged to outreach_log.json so the script never contacts
the same person twice, even across restarts.

Run with:
  py -3 outreach.py

Configure in .env:
  OUTREACH_KEYWORDS=Python engineer AI    — who to search for
  OUTREACH_NETWORK=S,O                    — S=2nd degree, O=3rd+ (comma-separated)
  OUTREACH_DAILY_LIMIT=5                  — max requests per calendar day
  OUTREACH_YOUR_ROLE=Software engineer    — brief description of yourself (for note tone)
  OUTREACH_REASON=explore collaboration   — why you're connecting (for note tone)

Requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env (Voyager credentials).
"""

import json
import logging
import os
from datetime import date

import llm
from dotenv import load_dotenv

import voyager as v

load_dotenv()

LOG_FILE = os.path.join(os.path.dirname(__file__), "outreach_log.json")

DAILY_LIMIT = int(os.environ.get("OUTREACH_DAILY_LIMIT", "5"))
OUTREACH_KEYWORDS = os.environ.get("OUTREACH_KEYWORDS", "Software engineer")
OUTREACH_NETWORK = os.environ.get("OUTREACH_NETWORK", "S")  # S=2nd, O=3rd+
YOUR_ROLE = os.environ.get("OUTREACH_YOUR_ROLE", "software professional")
OUTREACH_REASON = os.environ.get("OUTREACH_REASON", "expand my professional network")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def _load_log() -> dict:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {"sent": [], "today_count": 0, "last_reset": ""}


def _save_log(data: dict) -> None:
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _sent_today(data: dict) -> int:
    """Return today's send count, resetting the counter if the date has changed."""
    today = date.today().isoformat()
    if data.get("last_reset") != today:
        data["today_count"] = 0
        data["last_reset"] = today
    return data["today_count"]


def _already_sent(data: dict) -> set:
    return {r["public_id"] for r in data.get("sent", [])}


# ---------------------------------------------------------------------------
# Note generation
# ---------------------------------------------------------------------------

def _generate_note(first_name: str, headline: str) -> str:
    """Ask Gemini to write a personalised connection request (≤300 chars)."""
    return llm.generate(
        f"Write a LinkedIn connection request note.\n\n"
        f"Recipient: {first_name} — {headline}\n"
        f"Sender: {YOUR_ROLE} who wants to {OUTREACH_REASON}\n\n"
        "Requirements:\n"
        "- Maximum 300 characters (hard limit)\n"
        "- Reference something specific from their headline\n"
        "- Warm and genuine, not salesy\n"
        "- First person, from the sender\n"
        "- No emojis\n"
        "- Return only the message text, nothing else.",
        max_tokens=150,
    )[:300]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_outreach() -> None:
    data = _load_log()
    count = _sent_today(data)

    if count >= DAILY_LIMIT:
        log.info("Daily limit of %d already reached — nothing to do.", DAILY_LIMIT)
        return

    api = v._get_client()
    network_depths = [d.strip() for d in OUTREACH_NETWORK.split(",")]

    log.info("Searching for '%s' (network: %s)...", OUTREACH_KEYWORDS, network_depths)
    try:
        results = api.search_people(keywords=OUTREACH_KEYWORDS, network_depths=network_depths, limit=25)
    except Exception as e:
        log.error("search_people failed: %s", e)
        return

    sent_ids = _already_sent(data)
    log.info("Found %d candidates; %d already contacted.", len(results), len(sent_ids))

    for person in results:
        if count >= DAILY_LIMIT:
            log.info("Daily limit (%d) reached — stopping.", DAILY_LIMIT)
            break

        # Extract public_id — linkedin-api may return it under different keys
        public_id = (
            person.get("publicIdentifier")
            or person.get("public_id")
            or ""
        )
        if not public_id or public_id in sent_ids:
            continue

        # Fetch full profile for personalisation
        try:
            profile = api.get_profile(public_id=public_id)
        except Exception as e:
            log.warning("Could not fetch profile for %s: %s", public_id, e)
            continue

        first_name = profile.get("firstName", "there")
        last_name = profile.get("lastName", "")
        headline = profile.get("headline", "")

        note = _generate_note(first_name, headline)

        try:
            api.add_connection(public_id, message=note)
        except Exception as e:
            log.error("add_connection failed for %s: %s", public_id, e)
            continue

        log.info("Sent → %s %s | %s", first_name, last_name, note[:60] + "...")

        data["sent"].append(
            {
                "public_id": public_id,
                "name": f"{first_name} {last_name}".strip(),
                "headline": headline,
                "note": note,
                "sent_at": date.today().isoformat(),
            }
        )
        count += 1
        data["today_count"] = count
        _save_log(data)

    log.info("Done — sent %d request(s) today.", count)


if __name__ == "__main__":
    run_outreach()
