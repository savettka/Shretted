"""
Accounts, passwords and API tokens.

Passwords go through Werkzeug's scrypt (it ships with Flask, so nothing extra
to install). API tokens are for the iOS app: the token itself is shown once
and only its SHA-256 is stored, so a stolen database does not hand over
anybody's login.
"""
import hashlib
import hmac
import re
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD = 8
MAX_PASSWORD = 200


class AuthError(Exception):
    """Message is safe to show the user."""


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    if not stored_hash or not password:
        return False
    try:
        return check_password_hash(stored_hash, password)
    except (ValueError, TypeError):
        return False


def clean_email(value):
    return (value or "").strip().lower()


def check_signup(name, email, password, confirm):
    """Validate a signup form. Raises AuthError with something readable."""
    name = (name or "").strip()
    email = clean_email(email)

    if len(name) < 2:
        raise AuthError("Enter your name.")
    if len(name) > 60:
        raise AuthError("That name is too long.")
    if not EMAIL_RE.match(email) or len(email) > 200:
        raise AuthError("That does not look like an email address.")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError("Use at least " + str(MIN_PASSWORD) + " characters.")
    if len(password or "") > MAX_PASSWORD:
        raise AuthError("That password is too long.")
    if confirm is not None and password != confirm:
        raise AuthError("The two passwords do not match.")

    return name, email


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------

def new_token():
    """Returns (token, token_hash). Only the hash is ever stored."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def tokens_match(stored, candidate):
    return hmac.compare_digest(stored or "", token_hash(candidate))


def bearer_from(headers):
    """Pull the token out of an Authorization: Bearer <token> header."""
    raw = headers.get("Authorization", "")
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    return token or None
