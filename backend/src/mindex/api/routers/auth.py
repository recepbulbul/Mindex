"""`/auth`: register, log in and read the current user (F1)."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mindex.api.deps import CurrentUser, SessionDep, SettingsDep
from mindex.api.schemas import LoginRequest, LoginResponse, RegisterRequest, UserOut
from mindex.api.security import (
    dummy_hash,
    hash_password,
    issue_token,
    needs_rehash,
    verify_password,
)
from mindex.db.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])

BAD_CREDENTIALS = "E-posta veya parola hatalı."
EMAIL_TAKEN = "Bu e-posta ile kayıtlı bir hesap var."


def _response(settings: SettingsDep, user: User) -> LoginResponse:
    return LoginResponse(
        token=issue_token(settings, user.id, user.role), user=UserOut.model_validate(user)
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "E-posta kullanımda"}},
)
def register(body: RegisterRequest, session: SessionDep, settings: SettingsDep) -> LoginResponse:
    """Self-service sign-up always creates a `viewer`; researchers are created by an operator
    (`mindex create-user --role researcher`), so nobody can grant themselves write access."""
    user = User(email=body.email, password_hash=hash_password(body.password), role=UserRole.VIEWER)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"detail": EMAIL_TAKEN, "fields": {"email": EMAIL_TAKEN}}
        ) from None
    session.refresh(user)
    return _response(settings, user)


@router.post("/login", responses={status.HTTP_401_UNAUTHORIZED: {"description": BAD_CREDENTIALS}})
def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> LoginResponse:
    user = session.scalar(select(User).where(User.email == body.email))
    if user is None:
        verify_password(dummy_hash(), body.password)  # same cost as a real check
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        session.commit()
    return _response(settings, user)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
