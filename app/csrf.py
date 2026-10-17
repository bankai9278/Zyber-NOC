"""CSRF checks for form submissions.

Flask stores a random token in the signed session cookie. A form must
send that same token back. Another website cannot read the cookie, so it
cannot submit a valid form to this app.
"""

import secrets

from flask import request, session


def current_csrf_token():
    """Return the session token, creating one the first time it is needed."""
    token = session.get("csrf_token")
    if not isinstance(token, str) or token == "":
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def rejected_csrf():
    """Return True when a state-changing request did not send the session token."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return False
    submitted = request.form.get("csrf_token", "")
    return not _tokens_match(session.get("csrf_token"), submitted)


def _tokens_match(expected, submitted):
    if not isinstance(expected, str) or not isinstance(submitted, str):
        return False
    if expected == "" or len(expected) != len(submitted):
        return False
    return secrets.compare_digest(expected, submitted)
