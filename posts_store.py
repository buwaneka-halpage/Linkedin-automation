"""
Local post store — persists post metadata to posts.json.

Since LinkedIn's consumer API does not provide r_member_social scope,
we cannot read posts back from the API. Instead, every post created via
this tool is saved here, making it the source of truth for post history.

Note: posts created outside this tool (LinkedIn web, mobile, other apps)
will not appear here.
"""

import json
import os
import datetime

POSTS_FILE = os.path.join(os.path.dirname(__file__), "posts.json")


def _load() -> list:
    if not os.path.exists(POSTS_FILE):
        return []
    with open(POSTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(posts: list) -> None:
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)


def save_post(post: dict) -> None:
    """Prepend a new post record to posts.json (newest first)."""
    posts = _load()
    record = {
        "post_id":     post.get("post_id", ""),
        "post_url":    post.get("post_url", ""),
        "text":        post.get("text", ""),
        "type":        post.get("type", "NONE"),
        "article_url": post.get("article_url", ""),
        "visibility":  post.get("visibility", "PUBLIC"),
        "created":     datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    posts.insert(0, record)
    _save(posts)


def load_posts(count: int = 10) -> list:
    """Return the most recent `count` posts from local store."""
    return _load()[:count]


def post_count() -> int:
    return len(_load())
