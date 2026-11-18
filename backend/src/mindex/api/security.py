"""Password hashing (Argon2id) and access tokens (JWT, HS256) for F1 / NF3."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, cast

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from mindex.config import Settings
from mindex.db.models import UserRole

ALGORITHM = "HS256"
ISSUER = "mindex"


@lru_cache
def _hasher() -> PasswordHasher:
    # argon2-cffi defaults follow RFC 9106's second recommended profile and use Argon2id.
    return PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than today's defaults."""
    return _hasher().check_needs_rehash(password_hash)


@lru_cache
def dummy_hash() -> str:
    """Verified against when the e-mail is unknown, so a login takes the same time either way
    and response timing does not reveal which addresses are registered."""
    return hash_password(uuid.uuid4().hex)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    role: UserRole


class InvalidTokenError(Exception):
    """The bearer token is missing, malformed, expired or signed with another key."""


def issue_token(settings: Settings, user_id: uuid.UUID, role: UserRole) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_token(settings: Settings, token: str) -> TokenClaims:
    try:
        payload = cast(
            dict[str, Any],
            jwt.decode(
                token,
                settings.jwt_secret.get_secret_value(),
                algorithms=[ALGORITHM],  # pinned: never accept "none" or an attacker's choice
                issuer=ISSUER,
                options={"require": ["sub", "role", "exp", "iat", "iss"]},
            ),
        )
        return TokenClaims(uuid.UUID(str(payload["sub"])), UserRole(str(payload["role"])))
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
