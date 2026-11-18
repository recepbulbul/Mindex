"""Request dependencies: settings, the current user and role checks (F1)."""

from collections.abc import Callable
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from mindex.api.security import InvalidTokenError, decode_token
from mindex.config import Settings, get_settings
from mindex.db.models import User, UserRole
from mindex.db.session import get_session
from mindex.services.runner import JobQueue

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_bearer = HTTPBearer(auto_error=False)  # we raise our own 401 in the {detail} envelope

UNAUTHENTICATED = "Oturum gerekli."
FORBIDDEN = "Bu işlem için yetkiniz yok."


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"}
    )


def current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = decode_token(settings, credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized() from None
    user = session.get(User, claims.user_id)
    if user is None:  # deleted since the token was issued
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: 403 unless the current user has one of `roles`.

    The role is read from the database, not the token, so a demotion takes effect at once.
    """

    def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN)
        return user

    return check


Researcher = Annotated[User, Depends(require_role(UserRole.RESEARCHER))]


RUNNER_DOWN = "Deney koşucusu bu süreçte çalışmıyor."


def get_job_queue(request: Request) -> JobQueue:
    """The queue `create_server_app` starts; plain `create_app()` (tests, tools) has none."""
    jobs = cast(JobQueue | None, getattr(request.app.state, "job_queue", None))
    if jobs is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, RUNNER_DOWN)
    return jobs


JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]
