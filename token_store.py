import json
import os
import time
from config import TOKENS_FILE


def save_tokens(tokens: dict) -> None:
    """Persist tokens to disk."""
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def load_tokens() -> dict | None:
    """Load tokens from disk. Returns None if file doesn't exist."""
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE) as f:
        return json.load(f)


def tokens_valid() -> bool:
    """Return True if a non-expired access token exists."""
    tokens = load_tokens()
    if not tokens:
        return False
    expires_at = tokens.get("expires_at", 0)
    # Consider expired 5 minutes early
    return time.time() < (expires_at - 300)


def token_status() -> dict:
    """Return human-readable status of stored tokens."""
    tokens = load_tokens()
    if not tokens:
        return {"authenticated": False, "reason": "No tokens found. Run linkedin_authenticate."}
    expires_at = tokens.get("expires_at", 0)
    remaining = expires_at - time.time()
    if remaining <= 0:
        return {"authenticated": False, "reason": "Access token expired. Re-run linkedin_authenticate."}
    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)
    return {
        "authenticated": True,
        "expires_in": f"{hours}h {minutes}m",
        "person_urn": tokens.get("person_urn", "not cached yet"),
    }
