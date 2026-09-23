"""One-time Yahoo OAuth2 authorization, split into two non-interactive steps.

    python auth.py url           # print the Yahoo login URL
    python auth.py <code>        # exchange the code from the redirect for tokens

Tokens are written back into oauth2.json (gitignored) in the format yahoo_oauth
expects, so it can refresh them automatically afterwards.
"""
import base64
import json
import sys
import time
from urllib.parse import urlencode

import requests

CREDS_FILE = "oauth2.json"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def load():
    with open(CREDS_FILE) as f:
        return json.load(f)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    creds = load()
    redirect = creds.get("callback_uri", "https://localhost:8080")

    if sys.argv[1] == "url":
        params = {
            "client_id": creds["consumer_key"],
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "fspt-r",  # Fantasy Sports read; not always granted implicitly
        }
        print(f"{AUTH_URL}?{urlencode(params)}")
        return

    basic = base64.b64encode(f"{creds['consumer_key']}:{creds['consumer_secret']}".encode()).decode()
    resp = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"code": sys.argv[1], "redirect_uri": redirect, "grant_type": "authorization_code"},
        timeout=30,
    )
    if not resp.ok:
        sys.exit(f"Token exchange failed ({resp.status_code}): {resp.text}")
    tok = resp.json()
    creds.update(
        access_token=tok["access_token"],
        refresh_token=tok["refresh_token"],
        token_type=tok["token_type"],
        token_time=time.time(),
    )
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    print("Authorized. Tokens saved to oauth2.json.")


if __name__ == "__main__":
    main()
