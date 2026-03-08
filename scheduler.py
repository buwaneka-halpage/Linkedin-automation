"""
Module 2: Scheduled LinkedIn post generation and publishing.

Uses Claude to generate a post on a configurable schedule, then publishes
it automatically via the LinkedIn OAuth API.

Run with:
  py -3 scheduler.py

Configure in .env:
  SCHEDULE_TIME=09:00          — 24h time to post daily (default: 09:00)
  POST_TOPIC=<topic or prompt> — what Claude should write about
  POST_VISIBILITY=PUBLIC       — PUBLIC or CONNECTIONS
"""

import os
import time
import logging
from datetime import datetime

import schedule
from anthropic import Anthropic
from dotenv import load_dotenv

import linkedin_api

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SCHEDULE_TIME = os.environ.get("SCHEDULE_TIME", "09:00")
POST_TOPIC = os.environ.get(
    "POST_TOPIC",
    "share a professional insight about software engineering, career growth, or technology trends",
)
POST_VISIBILITY = os.environ.get("POST_VISIBILITY", "PUBLIC")


def _generate_post_text() -> str:
    """Ask Claude to write a LinkedIn post on the configured topic."""
    client = Anthropic()
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a LinkedIn post about: {POST_TOPIC}\n\n"
                    "Requirements:\n"
                    "- Professional but conversational tone\n"
                    "- 150–300 words\n"
                    "- Add 3–5 relevant hashtags at the end\n"
                    "- No generic filler phrases like 'Excited to share'\n"
                    "- Write in first person, as the profile owner\n"
                    "- Return only the post text, nothing else."
                ),
            }
        ],
    )
    return message.content[0].text.strip()


def generate_and_publish() -> None:
    """Generate a post with Claude and publish it to LinkedIn."""
    log.info("Generating post — topic: %s", POST_TOPIC)
    try:
        post_text = _generate_post_text()
    except Exception as e:
        log.error("Claude generation failed: %s", e)
        return

    log.info("Publishing post (%d chars)...", len(post_text))
    try:
        result = linkedin_api.create_text_post(post_text, POST_VISIBILITY)
    except Exception as e:
        log.error("LinkedIn API error: %s", e)
        return

    if "error" in result:
        log.error("Post failed: %s", result["error"])
    else:
        log.info("Post published: %s", result.get("post_url", ""))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Scheduler started — posting daily at %s (topic: %s)", SCHEDULE_TIME, POST_TOPIC)

    schedule.every().day.at(SCHEDULE_TIME).do(generate_and_publish)

    # Run once immediately on startup so you can verify it works
    log.info("Running initial post now to verify configuration...")
    generate_and_publish()

    while True:
        schedule.run_pending()
        time.sleep(30)
