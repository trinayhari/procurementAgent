"""One-time helper: mint a Gmail API refresh token for sending RFQs.

Run this ONCE on your machine to get a refresh token, then paste the printed
values into your backend `.env` (or export them). After that the app exchanges
the refresh token for short-lived access tokens on its own — you never run this
again unless you revoke access.

Prerequisites (see the README block printed at the end for details):
  1. A Google Cloud project with the **Gmail API** enabled.
     2. An OAuth 2.0 Client ID of type **Desktop app**. Download its JSON.
  3. On the OAuth consent screen: add your Gmail address as a **test user**
     and add the scopes https://www.googleapis.com/auth/gmail.send and
     https://www.googleapis.com/auth/gmail.readonly (send RFQs + read quote replies)

Usage:
    cd backend
    .venv/bin/python scripts/mint_gmail_token.py path/to/client_secret.json

A browser window opens; click "Allow". The script prints the four env vars
the backend reads (all PROCUREAI_-prefixed).
"""
import json
import sys

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/mint_gmail_token.py <client_secret.json>")
        return 2

    secrets_path = sys.argv[1]
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Missing deps. Install them first:\n"
            '  .venv/bin/pip install "google-auth-oauthlib" "google-api-python-client"'
        )
        return 1

    with open(secrets_path) as fh:
        info = json.load(fh)
    # Desktop-app client secrets are nested under "installed".
    client = info.get("installed") or info.get("web") or {}
    client_id = client.get("client_id", "")
    client_secret = client.get("client_secret", "")

    flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes=SCOPES)
    # Opens the browser for consent and runs a tiny local server to catch the
    # redirect. access_type=offline + prompt=consent guarantees a refresh token.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    if not creds.refresh_token:
        print(
            "\nNo refresh token returned. Revoke prior access for this app at "
            "https://myaccount.google.com/permissions and re-run."
        )
        return 1

    print("\n" + "=" * 64)
    print("SUCCESS — paste these into apps/api/.env")
    print("=" * 64)
    print(f"PROCUREAI_GMAIL_CLIENT_ID={client_id}")
    print(f"PROCUREAI_GMAIL_CLIENT_SECRET={client_secret}")
    print(f"PROCUREAI_GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("PROCUREAI_GMAIL_SENDER_ADDRESS=you@gmail.com  # <-- set your address")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
