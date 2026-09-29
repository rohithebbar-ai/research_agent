"""Authentication — resolves both channels to a canonical user_id.

Website (Entra ID):
- validate_entra_token(bearer_token) -> str:
    Validate the MSAL.js-issued Entra ID bearer token (via Easy Auth or
    explicit JWT validation). Returns canonical user_id.

WhatsApp (no interactive login):
- check_phone_allowlist(phone) -> str | None:
    Look up phone in the authorized_users container. Returns canonical
    user_id if authorized, else None.

Both paths converge on the same canonical user_id before Summarizer runs.
"""


def validate_entra_token(bearer_token: str) -> str:
    raise NotImplementedError


def check_phone_allowlist(phone: str) -> str | None:
    raise NotImplementedError
