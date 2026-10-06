"""Users, roles and login sessions. Standard library only: scrypt password hashes, server-side sessions behind an httponly cookie.

Roles: `superadmin` sees everything and manages users; `administrator` (the front-desk staff who process win-back cases) sees only the
pages of the Clients section.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import User, UserSession, now

COOKIE = "insights_session"
SESSION_DAYS = 14
ROLES = ("superadmin", "administrator")
DEFAULT_USER, DEFAULT_PASSWORD = "admin", "admin"      # created on first start; the app warns until the password is changed
PUBLIC = ("/login", "/static/", "/lang/", "/favicon.ico")
# What an administrator may open: the Clients section of the menu, a client's card, their own account.
ADMINISTRATOR_PREFIXES = ("/risk", "/outreach", "/cases", "/client/", "/account", "/logout")
HOME = {"superadmin": "/", "administrator": "/risk"}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        probe = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(probe.hex(), digest)
    except (ValueError, TypeError):
        return False


def ensure_admin(s: Session) -> bool:
    """On a fresh database, create admin/admin as the super-admin. Returns True when it was created."""
    if s.scalar(select(User.id).limit(1)) is not None:
        return False
    s.add(User(username=DEFAULT_USER, password_hash=hash_password(DEFAULT_PASSWORD), role="superadmin", active=True, must_change_password=True))
    s.flush()
    return True


def allowed(role: str, path: str) -> bool:
    if path.startswith(PUBLIC):
        return True
    if role == "superadmin":
        return True
    return role == "administrator" and path.startswith(ADMINISTRATOR_PREFIXES)


def authenticate(s: Session, username: str, password: str) -> User | None:
    u = s.scalar(select(User).where(User.username == username.strip().lower()))
    if u is None:                                         # spend the same time as a real check
        verify_password(hash_password("x"), password)
        return None
    return u if u.active and verify_password(u.password_hash, password) else None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(s: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    s.add(UserSession(token_hash=_hash_token(token), user_id=user.id, expires=now() + dt.timedelta(days=SESSION_DAYS)))
    user.last_login = now()
    s.execute(delete(UserSession).where(UserSession.expires < now()))        # tidy up old ones
    s.flush()
    return token


def user_for_token(s: Session, token: str | None) -> User | None:
    if not token:
        return None
    sess = s.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if sess is None or sess.expires.replace(tzinfo=dt.timezone.utc) < now():
        return None
    u = s.get(User, sess.user_id)
    return u if u and u.active else None


def end_session(s: Session, token: str | None) -> None:
    if token:
        s.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))


def set_password(s: Session, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.must_change_password = False
    s.execute(delete(UserSession).where(UserSession.user_id == user.id))      # signs the user out everywhere


def validate_password(password: str) -> str | None:
    """Why a new password is refused, or None. Short on purpose for now: staff passwords; the owner decides stricter rules when hosting."""
    if len(password) < 6:
        return "short"
    if password.lower() in {"admin", "password", "123456", "qwerty"}:
        return "common"
    return None
