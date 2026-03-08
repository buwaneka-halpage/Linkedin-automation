"""
LinkedIn OAuth 2.0 three-legged authorization flow.

Usage:
  tokens = run_oauth_flow()   # opens browser, starts local callback server
"""

import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

import config
from token_store import load_tokens, save_tokens


# ---------------------------------------------------------------------------
# Local callback server
# ---------------------------------------------------------------------------

_auth_result: dict = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        _auth_result["code"] = params.get("code", [None])[0]
        _auth_result["state"] = params.get("state", [None])[0]
        _auth_result["error"] = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if _auth_result.get("error"):
            body = f"<h2>Authorization failed: {_auth_result['error']}</h2><p>You can close this tab.</p>"
        else:
            body = "<h2>Authorization successful!</h2><p>You can close this tab and return to Claude.</p>"
        self.wfile.write(body.encode())

    def log_message(self, format, *args):  # silence access logs
        pass


def _start_callback_server() -> HTTPServer:
    server = HTTPServer(("localhost", config.REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Token exchange + refresh
# ---------------------------------------------------------------------------

def _exchange_code(code: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    resp = httpx.post(
        config.TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.REDIRECT_URI,
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token() -> dict:
    """Use the stored refresh_token to get a new access_token."""
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise RuntimeError("No refresh token available. Re-run linkedin_authenticate.")

    resp = httpx.post(
        config.TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    new_tokens = resp.json()
    merged = {**tokens, **new_tokens, "expires_at": time.time() + new_tokens["expires_in"]}
    save_tokens(merged)
    return merged


def get_valid_token() -> str:
    """Return a valid access token, refreshing if necessary."""
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated. Call linkedin_authenticate first.")

    expires_at = tokens.get("expires_at", 0)
    if time.time() >= (expires_at - 300):  # refresh 5 min early
        tokens = refresh_access_token()

    return tokens["access_token"]


# ---------------------------------------------------------------------------
# Main OAuth flow
# ---------------------------------------------------------------------------

def run_oauth_flow() -> dict:
    """
    Open browser for LinkedIn OAuth consent, wait for callback,
    exchange code, store tokens. Returns the saved token dict.
    """
    if not config.CLIENT_ID or not config.CLIENT_SECRET:
        raise RuntimeError(
            "LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env"
        )

    state = secrets.token_urlsafe(16)
    _auth_result.clear()

    params = {
        "response_type": "code",
        "client_id": config.CLIENT_ID,
        "redirect_uri": config.REDIRECT_URI,
        "scope": config.SCOPES,
        "state": state,
    }
    auth_url = f"{config.AUTH_URL}?{urlencode(params)}"

    server = _start_callback_server()
    print(f"\nOpening browser for LinkedIn login...\nIf the browser does not open, visit this URL manually:\n\n  {auth_url}\n", flush=True)
    webbrowser.open(auth_url)

    # Wait up to 300 seconds for the callback
    deadline = time.time() + 300
    while time.time() < deadline:
        if _auth_result.get("code") or _auth_result.get("error"):
            break
        time.sleep(0.2)
    else:
        server.shutdown()
        raise TimeoutError("OAuth flow timed out (5 min). Re-run linkedin_authenticate.")

    server.shutdown()

    if _auth_result.get("error"):
        raise RuntimeError(f"OAuth error: {_auth_result['error']}")

    if _auth_result.get("state") != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF attack.")

    token_data = _exchange_code(_auth_result["code"])
    tokens = {
        **token_data,
        "expires_at": time.time() + token_data["expires_in"],
    }
    save_tokens(tokens)
    return tokens
