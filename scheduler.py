"""
Module 2: LinkedIn post generation and publishing.

Generates a post with Gemini and publishes it via the LinkedIn OAuth API.
Designed to be triggered by Windows Task Scheduler (or any OS scheduler)
once per day — it runs, publishes, and exits. No long-running process needed.

Run manually:
  py -3 scheduler.py

Schedule with Windows Task Scheduler (run once to register):
  schtasks /create /tn "LinkedIn Daily Post" ^
    /tr "\".venv\\Scripts\\python.exe\" \"scheduler.py\"" ^
    /sc daily /st 09:00 /f

Configure in .env:
  POST_TOPIC=<topic or prompt> — what Gemini should write about
  POST_VISIBILITY=PUBLIC       — PUBLIC or CONNECTIONS
"""

import logging
import os

import llm
import linkedin_api
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

POST_TOPIC = os.environ.get(
    "POST_TOPIC",
    "share a professional insight about software engineering, career growth, or technology trends",
)
POST_VISIBILITY = os.environ.get("POST_VISIBILITY", "PUBLIC")


def _generate_post_text() -> str:
    """Ask Gemini to write a LinkedIn post on the configured topic."""
    return llm.generate(
        f"Write a LinkedIn post about: {POST_TOPIC}\n\n"
        "Requirements:\n"
        "- Professional but conversational tone\n"
        "- 150-300 words\n"
        "- Add 3-5 relevant hashtags at the end\n"
        "- No generic filler phrases like 'Excited to share'\n"
        "- Write in first person, as the profile owner\n"
        "- Return only the post text, nothing else.",
        max_tokens=512,
    )


def generate_and_publish() -> None:
    log.info("Generating post — topic: %s", POST_TOPIC)
    try:
        post_text = _generate_post_text()
    except Exception as e:
        log.error("Gemini generation failed: %s", e)
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


if __name__ == "__main__":
    generate_and_publish()
