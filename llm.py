"""
Thin Gemini wrapper — all LLM calls in the project go through here.

Every module (scheduler, outreach, job_scorer) calls llm.generate(prompt).
To swap providers, only this file needs to change.

Requires GEMINI_API_KEY in .env.
Get a free key at https://aistudio.google.com/apikey
"""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in .env")
        _client = genai.Client(api_key=api_key)
    return _client


def generate(prompt: str, max_tokens: int = 1024) -> str:
    """Send a prompt to Gemini 2.5 Flash and return the response text."""
    response = _get_client().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    return response.text.strip()
