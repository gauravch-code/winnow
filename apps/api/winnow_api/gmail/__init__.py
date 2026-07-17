"""Gmail integration package.

Import-time gate: this module is real-mode-only. Importing it under
WINNOW_MODE=demo raises ImportError, which is what keeps the demo
backend from ever pulling Gmail code into its process image. The
demo has no OAuth secrets, no refresh tokens, and no reason to touch
Gmail — the import guard makes that a machine-enforced invariant
rather than a docs-only rule.
"""

from __future__ import annotations

from winnow_api.config import get_settings

_mode = get_settings().mode
if _mode != "real":
    raise ImportError(
        f"winnow_api.gmail is real-mode only; refusing to import under WINNOW_MODE={_mode}. "
        "If a demo-mode module is importing this, that is a bug — file it."
    )

# Below this line runs only in real mode.

from winnow_api.gmail.client import GmailClient  # noqa: E402
from winnow_api.gmail.ingest import ingest_message  # noqa: E402
from winnow_api.gmail.oauth import (  # noqa: E402
    OAUTH_SCOPES,
    authorize_installed_app,
    load_credentials_for_user,
)
from winnow_api.gmail.sync import GmailSync  # noqa: E402

__all__ = [
    "OAUTH_SCOPES",
    "GmailClient",
    "GmailSync",
    "authorize_installed_app",
    "ingest_message",
    "load_credentials_for_user",
]
