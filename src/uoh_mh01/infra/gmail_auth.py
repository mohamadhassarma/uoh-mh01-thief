"""OAuth 2.0 credential handling for the send-only Gmail scope (Appendix A).

BOTH SECRETS LIVE OUTSIDE BOTH REPOS, at `C:\\dev\\uni\\secrets\\`, and are
referenced by path — never copied in, never read into a repo file. Appendix A
is blunt about why: pushing `credentials.json` or `token.json` "שקולה לפרסום
מפתח הכניסה לתיבת הדואר שלכם ברשות הרבים", and once a secret is in even one
commit, deleting it later is not enough — the credential must be rotated in
the console. Keeping them outside the working tree means no `.gitignore` rule
has to hold for that to stay true; the rules are still there as a second line.

THE CONSENT FLOW IS NEVER RUN IMPLICITLY. `load_credentials` will refresh an
existing token silently (that is what the refresh token is for, and it needs
no human), but it will NOT open a browser. A report send that could pop a
consent screen mid-run is a report send that can hang forever on a headless
box. Authorization is its own explicit, human-invoked command: `authorize()`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .gmail_sender import GMAIL_SEND_SCOPE

logger = logging.getLogger(__name__)

SECRETS_DIR = Path(r"C:\dev\uni\secrets")
CREDENTIALS_NAME = "credentials.json"
TOKEN_NAME = "token.json"

SCOPES = [GMAIL_SEND_SCOPE]


class NotAuthorizedError(Exception):
    """No usable token. Carries the exact command a human must run."""


def credentials_path(secrets_dir: Path | None = None) -> Path:
    return (secrets_dir or SECRETS_DIR) / CREDENTIALS_NAME


def token_path(secrets_dir: Path | None = None) -> Path:
    return (secrets_dir or SECRETS_DIR) / TOKEN_NAME


def load_credentials(secrets_dir: Path | None = None):
    """Return usable credentials, refreshing if needed. Never opens a browser."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = token_path(secrets_dir)
    if not token.is_file():
        raise NotAuthorizedError(
            f"no {TOKEN_NAME} at {token} — run `uoh-mh01 authorize-gmail` once, "
            "in a session where a browser can open, and approve the send-only scope"
        )
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        # The whole point of the refresh token (Appendix A §2): months of
        # autonomous sends with no further human step.
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
        return creds
    raise NotAuthorizedError(f"{token} is no longer usable and has no refresh token — re-run `uoh-mh01 authorize-gmail`")


def authorize(secrets_dir: Path | None = None) -> Path:
    """Run the consent flow ONCE, interactively, and write `token.json` beside
    `credentials.json`. Only ever called from the explicit CLI command."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_file = credentials_path(secrets_dir)
    if not creds_file.is_file():
        raise NotAuthorizedError(f"no {CREDENTIALS_NAME} at {creds_file} — download it from the Google Cloud console")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)
    out = token_path(secrets_dir)
    out.write_text(creds.to_json(), encoding="utf-8")
    logger.info("wrote %s", out)
    return out


def gmail_service(secrets_dir: Path | None = None):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=load_credentials(secrets_dir), cache_discovery=False)
