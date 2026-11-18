import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mindex import cli
from mindex.api import security
from mindex.api.app import create_app
from mindex.api.deps import require_role
from mindex.api.routers.auth import BAD_CREDENTIALS, EMAIL_TAKEN
from mindex.config import Settings, get_settings
from mindex.db.models import User, UserRole
from mindex.db.session import get_session

# `_env_file` is a pydantic-settings init kwarg pyright cannot see (same as test_config.py).
SETTINGS = Settings(_env_file=None, jwt_secret=SecretStr("x" * 64), jwt_ttl_minutes=5)  # pyright: ignore[reportCallIssue]
PASSWORD = "dogru-parola-123"


# ---------------------------------------------------------------- unit: hashing and tokens


def test_passwords_are_hashed_with_argon2id() -> None:
    h = security.hash_password(PASSWORD)
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, PASSWORD)
    assert not security.verify_password(h, "yanlis-parola")
    assert not security.verify_password("not-a-hash", PASSWORD)
    assert not security.needs_rehash(h)


def test_token_roundtrip() -> None:
    uid = uuid.uuid4()
    claims = security.decode_token(SETTINGS, security.issue_token(SETTINGS, uid, UserRole.VIEWER))
    assert claims == security.TokenClaims(uid, UserRole.VIEWER)


def _forge(payload: dict[str, Any], key: str = "x" * 64, alg: str = "HS256") -> str:
    return jwt.encode(payload, key, algorithm=alg)


def _claims(**over: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "role": "researcher",
        "iss": "mindex",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return {k: v for k, v in {**base, **over}.items() if v is not None}


@pytest.mark.parametrize(
    "token",
    [
        _forge(_claims(exp=datetime.now(UTC) - timedelta(seconds=1))),  # expired
        _forge(_claims(), key="y" * 40),  # wrong key
        _forge(_claims(iss="someone-else")),  # wrong issuer
        _forge(_claims(role="admin")),  # unknown role
        _forge(_claims(sub="not-a-uuid")),  # malformed subject
        _forge(_claims(exp=None)),  # no expiry
        _forge(_claims(), alg="HS512"),  # algorithm not allowed
        "garbage",
    ],
)
def test_bad_tokens_are_rejected(token: str) -> None:
    with pytest.raises(security.InvalidTokenError):
        security.decode_token(SETTINGS, token)


def test_unsigned_token_is_rejected() -> None:
    unsigned = jwt.encode(_claims(), key=None, algorithm="none")  # pyright: ignore[reportArgumentType]
    with pytest.raises(security.InvalidTokenError):
        security.decode_token(SETTINGS, unsigned)


@pytest.mark.parametrize("secret", ["change-me", "short-but-not-default"])
def test_production_refuses_weak_jwt_secret(secret: str) -> None:
    with pytest.raises(ValidationError, match="MINDEX_JWT_SECRET"):
        Settings(_env_file=None, env="production", jwt_secret=SecretStr(secret))  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("env", ["test", "production"])
def test_placeholder_secret_refused_outside_development(env: str) -> None:
    with pytest.raises(ValidationError, match="MINDEX_JWT_SECRET"):
        Settings(_env_file=None, env=env, jwt_secret=SecretStr("change-me"))  # pyright: ignore[reportCallIssue]


def test_placeholder_secret_allowed_in_development() -> None:
    assert Settings(_env_file=None, env="development").env == "development"  # pyright: ignore[reportCallIssue]


def test_production_accepts_strong_secret() -> None:
    s = Settings(_env_file=None, env="production", jwt_secret=SecretStr("z" * 48))  # pyright: ignore[reportCallIssue]
    assert s.env == "production"


# ---------------------------------------------------------------- API (needs the database)


@pytest.fixture
def api(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    @app.post("/api/_researcher-only")
    def researcher_only(  # pyright: ignore[reportUnusedFunction]
        user: Annotated[User, Depends(require_role(UserRole.RESEARCHER))],
    ) -> dict[str, str]:
        return {"email": user.email}

    def session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    with TestClient(app) as c:
        yield c


def _add_user(session: Session, email: str, role: UserRole) -> User:
    user = User(email=email, password_hash=security.hash_password(PASSWORD), role=role)
    session.add(user)
    session.commit()
    return user


def _token(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return cast(str, res.json()["token"])


@pytest.mark.db
def test_register_creates_a_viewer_and_logs_in(api: TestClient, db_session: Session) -> None:
    res = api.post("/api/auth/register", json={"email": "Yeni@Mindex.dev", "password": PASSWORD})
    assert res.status_code == 201
    body = res.json()
    assert body["user"] == {"email": "yeni@mindex.dev", "role": "viewer"}
    assert security.decode_token(SETTINGS, body["token"]).role is UserRole.VIEWER
    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.json() == {"email": "yeni@mindex.dev", "role": "viewer"}
    # The stored row holds an Argon2id hash, not the password, and the same credentials log in.
    row = db_session.scalar(select(User).where(User.email == "yeni@mindex.dev"))
    assert row is not None
    assert row.password_hash.startswith("$argon2id$")
    assert PASSWORD not in row.password_hash
    _token(api, "yeni@mindex.dev")


@pytest.mark.db
def test_register_ignores_requested_role(api: TestClient) -> None:
    res = api.post(
        "/api/auth/register",
        json={"email": "a@mindex.dev", "password": PASSWORD, "role": "researcher"},
    )
    assert res.status_code == 422  # unknown field, not a silent privilege grant


@pytest.mark.db
def test_register_duplicate_email_is_409_case_insensitive(
    api: TestClient, db_session: Session
) -> None:
    _add_user(db_session, "var@mindex.dev", UserRole.VIEWER)
    res = api.post("/api/auth/register", json={"email": "VAR@mindex.dev", "password": PASSWORD})
    assert res.status_code == 409
    assert res.json() == {"detail": EMAIL_TAKEN, "fields": {"email": EMAIL_TAKEN}}


@pytest.mark.db
@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": "k@mindex.dev", "password": "kisa"}, "password"),
        ({"email": "k@mindex.dev", "password": "p" * 129}, "password"),
    ],
)
def test_register_validates_input(api: TestClient, payload: dict[str, str], field: str) -> None:
    res = api.post("/api/auth/register", json=payload)
    assert res.status_code == 422
    assert field in res.json()["fields"]


@pytest.mark.db
@pytest.mark.parametrize(
    ("email", "password"),
    [("kayitli@mindex.dev", "yanlis-parola"), ("yok@mindex.dev", PASSWORD)],
)
def test_login_failures_look_the_same(
    api: TestClient, db_session: Session, email: str, password: str
) -> None:
    _add_user(db_session, "kayitli@mindex.dev", UserRole.VIEWER)
    res = api.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 401
    assert res.json() == {"detail": BAD_CREDENTIALS}


@pytest.mark.db
def test_login_with_unknown_email_still_verifies_a_hash(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def spy(password_hash: str, password: str) -> bool:
        calls.append(password_hash)
        return security.verify_password(password_hash, password)

    monkeypatch.setattr("mindex.api.routers.auth.verify_password", spy)
    res = api.post("/api/auth/login", json={"email": "yok@mindex.dev", "password": PASSWORD})
    assert res.status_code == 401
    assert calls == [security.dummy_hash()]  # same Argon2 cost as a registered e-mail


@pytest.mark.db
def test_login_rehashes_outdated_hash(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _add_user(db_session, "eski@mindex.dev", UserRole.VIEWER)
    old_hash = user.password_hash

    def outdated(_: str) -> bool:
        return True

    monkeypatch.setattr(security, "needs_rehash", outdated)
    monkeypatch.setattr("mindex.api.routers.auth.needs_rehash", outdated)
    _token(api, "eski@mindex.dev")
    db_session.refresh(user)
    assert user.password_hash != old_hash
    assert security.verify_password(user.password_hash, PASSWORD)


@pytest.mark.db
@pytest.mark.parametrize(
    "header",
    [None, "Bearer garbage", "Basic Zm9vOmJhcg=="],
)
def test_me_requires_a_valid_bearer_token(api: TestClient, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    res = api.get("/api/auth/me", headers=headers)
    assert res.status_code == 401
    assert res.json() == {"detail": "Oturum gerekli."}
    assert res.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.db
def test_token_of_deleted_user_is_rejected(api: TestClient, db_session: Session) -> None:
    user = _add_user(db_session, "silinen@mindex.dev", UserRole.VIEWER)
    token = _token(api, "silinen@mindex.dev")
    db_session.delete(user)
    db_session.commit()
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.db
def test_viewer_gets_403_researcher_passes(api: TestClient, db_session: Session) -> None:
    _add_user(db_session, "izleyici@mindex.dev", UserRole.VIEWER)
    _add_user(db_session, "arastirmaci@mindex.dev", UserRole.RESEARCHER)
    viewer = {"Authorization": f"Bearer {_token(api, 'izleyici@mindex.dev')}"}
    researcher = {"Authorization": f"Bearer {_token(api, 'arastirmaci@mindex.dev')}"}
    denied = api.post("/api/_researcher-only", headers=viewer)
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Bu işlem için yetkiniz yok."}
    assert api.post("/api/_researcher-only", headers=researcher).status_code == 200


@pytest.mark.db
def test_demotion_applies_immediately(api: TestClient, db_session: Session) -> None:
    user = _add_user(db_session, "terfi@mindex.dev", UserRole.RESEARCHER)
    headers = {"Authorization": f"Bearer {_token(api, 'terfi@mindex.dev')}"}
    user.role = UserRole.VIEWER
    db_session.commit()
    assert api.post("/api/_researcher-only", headers=headers).status_code == 403


# ---------------------------------------------------------------- CLI


@pytest.fixture
def cli_sessions(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    factory = sessionmaker(bind=db_session.connection(), join_transaction_mode="create_savepoint")
    monkeypatch.setattr("mindex.db.session.get_sessionmaker", lambda: factory)
    return db_session


@pytest.mark.db
def test_cli_creates_researcher(cli_sessions: Session) -> None:
    cli.create_user("Hoca@Mindex.dev", "researcher", password=PASSWORD)
    user = cli_sessions.scalar(select(User).where(User.email == "hoca@mindex.dev"))
    assert user is not None
    assert user.role is UserRole.RESEARCHER
    assert security.verify_password(user.password_hash, PASSWORD)


@pytest.mark.db
def test_cli_rejects_duplicate_and_weak_password(cli_sessions: Session) -> None:
    cli.create_user("iki@mindex.dev", "viewer", password=PASSWORD)
    with pytest.raises(SystemExit, match="zaten kayıtlı"):
        cli.create_user("iki@mindex.dev", "viewer", password=PASSWORD)
    with pytest.raises(SystemExit, match="Geçersiz") as rejected:
        cli.create_user("uc@mindex.dev", "viewer", password="kisa-pw")
    message = str(rejected.value)
    assert "password" in message
    assert "kisa-pw" not in message  # the rejected password is never echoed


def test_cli_reads_piped_password_keeping_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the line ending is dropped: leading/trailing spaces are part of the password.
    monkeypatch.setattr("sys.stdin", io.StringIO("  bosluklu parola \r\nikinci satir\n"))
    assert cli._read_password() == "  bosluklu parola "  # pyright: ignore[reportPrivateUsage]


def test_auth_routes_are_in_openapi() -> None:
    paths = TestClient(create_app()).get("/api/openapi.json").json()["paths"]
    assert {"/api/auth/register", "/api/auth/login", "/api/auth/me"} <= set(paths)
