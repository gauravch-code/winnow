"""Gmail OAuth (installed-app / desktop client flow).

Chosen over the web-app flow because Winnow is single-user: the owner
downloads a desktop-client credentials.json from Google Cloud Console
once, runs ``winnow gmail authorize``, clicks through Google's consent
screen in a local browser, and Google redirects to a loopback address
this CLI listens on. No public callback URL to host, no client secret
in a web frontend, no session cookies to manage.

Only the refresh token is persisted (Fernet-encrypted). The short-lived
access token is regenerated on demand by google-auth's ``Credentials``
class using that refresh token.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from sqlalchemy.orm import Session

from winnow_api.db.models import User
from winnow_api.security import decrypt, encrypt

log = structlog.get_logger(__name__)

# gmail.modify is the minimum scope Winnow needs: read messages, and
# add/remove labels when the user's actions in the dashboard should
# reflect back to Gmail. Read-only would forbid the label reflection.
OAUTH_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def authorize_installed_app(
    db: Session,
    user: User,
    credentials_file: Path,
    open_browser: bool = True,
) -> None:
    """Run the installed-app OAuth flow and store the refresh token.

    Overwrites any existing token — re-authorizing is the intended
    remedy for a lost or rotated key, and asking for confirmation here
    would just add a step to a rare, deliberate operation.
    """
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), OAUTH_SCOPES)
    # port=0 lets the OS pick a free port; access_type='offline' + prompt='consent'
    # force Google to actually return a refresh token even on re-auth (otherwise
    # it may omit it if the user already granted access from this client).
    creds = flow.run_local_server(
        port=0,
        open_browser=open_browser,
        access_type="offline",
        prompt="consent",
    )
    if not creds.refresh_token:
        raise RuntimeError(
            "OAuth flow returned no refresh_token. Revoke the previous grant at "
            "https://myaccount.google.com/permissions and re-run."
        )

    user.gmail_refresh_token_encrypted = encrypt(creds.refresh_token)
    # Stash the client id/secret in gmail_state so we don't need
    # credentials.json on every sync — self-contained per-user config.
    state = dict(user.gmail_state or {})
    state["oauth"] = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or OAUTH_SCOPES),
    }
    user.gmail_state = state
    db.commit()
    log.info("gmail_oauth_authorized", user_id=str(user.id), email=user.email)


def load_credentials_for_user(user: User) -> Credentials:
    """Reconstruct a live ``Credentials`` object from persisted state.

    google-auth handles access-token refresh transparently on the first
    API call after this is returned, so callers can just do
    ``build('gmail', 'v1', credentials=creds)`` and forget about token
    lifecycle.
    """
    if not user.gmail_refresh_token_encrypted:
        raise RuntimeError(
            "No Gmail refresh token stored for this user. Run `winnow gmail authorize` first."
        )
    oauth = (user.gmail_state or {}).get("oauth")
    if not oauth:
        raise RuntimeError(
            "gmail_state.oauth is empty — the user was authorized under an older code path. "
            "Re-run `winnow gmail authorize` to re-populate."
        )
    return Credentials(
        token=None,  # will be minted on first API call
        refresh_token=decrypt(user.gmail_refresh_token_encrypted),
        token_uri=oauth["token_uri"],
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"],
        scopes=oauth.get("scopes", OAUTH_SCOPES),
    )
