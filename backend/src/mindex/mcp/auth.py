"""Per-agent MCP credentials (NF3): a signed token that names exactly one agent.

The token is a JWT signed with the same key as user tokens (`MINDEX_JWT_SECRET`) but with
its own audience, so neither kind is accepted in place of the other. The agent's identity
comes from the token alone; no tool argument can change whose portfolio a call touches.
"""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta

import jwt
from mcp.server.auth.provider import AccessToken

from mindex.api.security import ALGORITHM, ISSUER, InvalidTokenError
from mindex.config import Settings

AUDIENCE = "mindex-mcp"


def issue_agent_token(settings: Settings, agent_id: str, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {"sub": agent_id, "aud": AUDIENCE, "iss": ISSUER, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_agent_token(settings: Settings, token: str) -> tuple[str, int]:
    """The agent the token names and its expiry (epoch seconds)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],  # pinned, as for user tokens
            issuer=ISSUER,
            audience=AUDIENCE,  # a user token has no audience and is refused here
            options={"require": ["sub", "aud", "exp", "iat", "iss"]},
        )
        return str(payload["sub"]), int(payload["exp"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


class AgentTokenVerifier:
    """The MCP SDK's `TokenVerifier`: valid tokens of this session's agents only (else 401)."""

    def __init__(self, settings: Settings, agent_ids: Collection[str]) -> None:
        self._settings = settings
        self._agent_ids = agent_ids

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            agent_id, expires_at = decode_agent_token(self._settings, token)
        except InvalidTokenError:
            return None
        if agent_id not in self._agent_ids:
            return None
        return AccessToken(token=token, client_id=agent_id, scopes=[], expires_at=expires_at)
