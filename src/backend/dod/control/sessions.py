"""Sessions and the internal key (docs/backend.md 9).

A visitor's identity is a random token in the `dod_session` cookie (128 bits).
The token is a secret: whoever has it holds that place in the queue. So it
never leaves this module and the cookie. Everything else – the queue, the
state, the logs on the public screen – uses the **public id**, a hash of the
token, and shows its first 4 characters (`7f3a`).

Not security, only fairness (tech-spec 4.6): an incognito window is a new
visitor. The internal key is the one real check: it guards the main screen.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping

SESSION_COOKIE = "dod_session"
INTERNAL_COOKIE = "dod_internal"
MAIN = "main"  # the main screen's id in commands and logs

TOKEN = re.compile(r"[0-9a-f]{32}")
SESSION_MAX_AGE = 12 * 3600  # one open day; a reload or the next morning keeps the place
PUBLIC_ID_LENGTH = 12  # hex characters: no collisions among a day's visitors
SHORT_LENGTH = 4


def new_token() -> str:
    return secrets.token_hex(16)


def valid_token(token: str | None) -> bool:
    return token is not None and TOKEN.fullmatch(token) is not None


def session_token(cookies: Mapping[str, str]) -> str | None:
    """The visitor's token from the request's cookies, if it is a valid one."""
    token = cookies.get(SESSION_COOKIE)
    return token if valid_token(token) else None


def public_id(token: str) -> str:
    """What the rest of the backend knows a visitor by. Can't be turned back into the token."""
    if not valid_token(token):
        raise ValueError("not a session token")
    return hashlib.sha256(token.encode("ascii")).hexdigest()[:PUBLIC_ID_LENGTH]


def short(who: str | None) -> str | None:
    """For screens and logs: `7f3a` for a visitor, `main` for the main screen."""
    if who is None or who == MAIN:
        return who
    return who[:SHORT_LENGTH]


def cookie_options() -> dict[str, object]:
    """For Response.set_cookie(SESSION_COOKIE, token, **cookie_options())."""
    return {"max_age": SESSION_MAX_AGE, "httponly": True, "samesite": "lax", "path": "/"}


def key_matches(given: str | None, key: str) -> bool:
    """The internal key check, in constant time."""
    if not given:
        return False
    return hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8"))
