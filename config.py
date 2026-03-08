import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_PORT = int(os.environ.get("LINKEDIN_REDIRECT_PORT", "8080"))
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"

SCOPES = "openid profile email w_member_social"

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com"

TOKENS_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")
