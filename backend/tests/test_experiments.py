"""Experiment management API (F2): CRUD, validation, the sealed test window, YAML round trip."""

import json
import re
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any, cast

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from mindex.agents.llm import PROMPT_VERSION
from mindex.api import security
from mindex.api.app import create_app
from mindex.api.routers.experiments import NOT_OWNER, SEALED, config_from_yaml, overlaps_test_window
from mindex.config import Settings, get_settings
from mindex.db.models import Experiment, ExperimentAgent, ExperimentStatus, User, UserRole
from mindex.db.session import get_session

SETTINGS = Settings(_env_file=None, jwt_secret=SecretStr("x" * 64), llm_model="test-model")  # pyright: ignore[reportCallIssue]
PASSWORD = "dogru-parola-123"
FRONTEND_AGENT_IDS = [
    "buy-hold-btc",
    "equal-weight",
    "ma-cross",
    "ppo",
    "llm-momentum",
    "llm-mean-reversion",
    "llm-sentiment",
    "llm-risk-averse",
    "mcp-guest",
]
CONFIG: dict[str, Any] = {
    "name": "Doğrulama · C1 · seed 2",
    "mode": "replay",
    "condition": "C1",
    "startDate": "2025-10-01",
    "endDate": "2026-03-31",
    "assets": ["BTC", "ETH"],
    "agentIds": ["llm-momentum", "buy-hold-btc"],  # order is kept, not sorted
    "seed": 2,
    "commissionRate": 0.001,
    "slippageBps": 5,
}
CONFIG_KEYS = list(CONFIG)

Headers = dict[str, str]

pytestmark = pytest.mark.db


@pytest.fixture
def api(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    def session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    with TestClient(app) as c:
        yield c


def _login(api: TestClient, session: Session, email: str, role: UserRole) -> Headers:
    session.add(User(email=email, password_hash=security.hash_password(PASSWORD), role=role))
    session.commit()
    res = api.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture
def researcher(api: TestClient, db_session: Session) -> Headers:
    return _login(api, db_session, "arastirmaci@mindex.dev", UserRole.RESEARCHER)


@pytest.fixture
def viewer(api: TestClient, db_session: Session) -> Headers:
    return _login(api, db_session, "izleyici@mindex.dev", UserRole.VIEWER)


def _create(api: TestClient, headers: Headers, **over: Any) -> dict[str, Any]:
    res = api.post("/api/experiments", json={**CONFIG, **over}, headers=headers)
    assert res.status_code == 201, res.text
    return cast(dict[str, Any], res.json())


def _config(exp: dict[str, Any]) -> dict[str, Any]:
    return {k: exp[k] for k in CONFIG_KEYS}


def _set_status(session: Session, exp_id: str, st: ExperimentStatus) -> None:
    row = session.get(Experiment, uuid.UUID(exp_id))
    assert row is not None
    row.status = st
    session.commit()


# ---------------------------------------------------------------- agents


def test_agents_are_seeded_with_frontend_ids(api: TestClient, viewer: Headers) -> None:
    res = api.get("/api/agents", headers=viewer)
    assert res.status_code == 200
    agents = res.json()
    assert sorted(a["id"] for a in agents) == sorted(FRONTEND_AGENT_IDS)
    momentum = next(a for a in agents if a["id"] == "llm-momentum")
    assert momentum == {
        "id": "llm-momentum",
        "name": "LLM · Momentum",
        "kind": "llm",
        "persona": "Trendi takip eder; güçlenen varlıklara ağırlık verir.",
    }


def test_agents_need_a_session(api: TestClient) -> None:
    assert api.get("/api/agents").status_code == 401


# ---------------------------------------------------------------- create and read


def test_create_returns_a_draft_with_versions(
    api: TestClient, researcher: Headers, db_session: Session
) -> None:
    exp = _create(api, researcher, name="  Kırpılan ad  ")
    assert exp["status"] == "draft"
    assert exp["name"] == "Kırpılan ad"
    assert exp["modelVersion"] == "test-model"
    assert exp["promptVersion"] == PROMPT_VERSION
    assert _config(exp) == {**CONFIG, "name": "Kırpılan ad", "slippageBps": 5.0}
    row = db_session.scalar(select(Experiment))
    assert row is not None
    assert (row.model_version, row.prompt_version) == ("test-model", PROMPT_VERSION)
    links = db_session.scalars(select(ExperimentAgent)).all()
    assert sorted(ea.agent.slug for ea in links) == ["buy-hold-btc", "llm-momentum"]


def test_list_and_get(api: TestClient, researcher: Headers, viewer: Headers) -> None:
    exp = _create(api, researcher)
    listed = api.get("/api/experiments", headers=viewer).json()
    assert [e["id"] for e in listed] == [exp["id"]]
    assert api.get(f"/api/experiments/{exp['id']}", headers=viewer).json() == exp


@pytest.mark.parametrize("bad_id", ["yok", "00000000-0000-0000-0000-000000000000"])
def test_unknown_experiment_is_404(api: TestClient, viewer: Headers, bad_id: str) -> None:
    res = api.get(f"/api/experiments/{bad_id}", headers=viewer)
    assert res.status_code == 404
    assert res.json() == {"detail": "Deney bulunamadı."}


# ---------------------------------------------------------------- validation (= zod schema)


@pytest.mark.parametrize(
    ("over", "field", "message"),
    [
        ({"name": "  ab "}, "name", "En az 3 karakter"),
        ({"name": "x" * 121}, "name", "En fazla 120 karakter"),
        ({"mode": "paper"}, "mode", None),
        ({"condition": "C9"}, "condition", None),
        ({"startDate": "01.10.2025"}, "startDate", "Tarih YYYY-AA-GG olmalı"),
        ({"startDate": "2025-02-30"}, "startDate", "Tarih YYYY-AA-GG olmalı"),
        ({"assets": []}, "assets", "En az bir varlık seçin"),
        ({"assets": ["DOGE"]}, "assets.0", None),
        ({"agentIds": ["ppo"]}, "agentIds", "En az iki ajan seçin"),
        ({"seed": 1.5}, "seed", "Tam sayı olmalı"),
        ({"seed": "5"}, "seed", "Tam sayı olmalı"),
        ({"seed": -1}, "seed", None),
        ({"seed": 2**31}, "seed", None),
        ({"commissionRate": 0.02}, "commissionRate", "En fazla %1"),
        ({"commissionRate": "0.001"}, "commissionRate", "Sayı olmalı"),
        ({"slippageBps": 101}, "slippageBps", "En fazla 100 bp"),
        ({"slippageBps": -1}, "slippageBps", None),
        ({"endDate": None}, "endDate", "Replay modunda bitiş tarihi zorunlu"),
        ({"endDate": "2025-10-01"}, "endDate", "Bitiş, başlangıçtan sonra olmalı"),
        ({"agentIds": ["ppo", "yok"]}, "agentIds", "Bilinmeyen ajan: yok"),
        ({"agentIds": ["ppo", "ppo"]}, "agentIds", None),
        ({"status": "completed"}, "status", None),  # unknown field, not a status override
    ],
)
def test_create_validates_like_the_form(
    api: TestClient, researcher: Headers, over: dict[str, Any], field: str, message: str | None
) -> None:
    res = api.post("/api/experiments", json={**CONFIG, **over}, headers=researcher)
    assert res.status_code == 422, res.text
    fields = res.json()["fields"]
    assert field in fields
    if message is not None:
        assert fields[field] == message


def test_nan_is_not_a_number(api: TestClient, researcher: Headers) -> None:
    body = json.dumps({**CONFIG, "commissionRate": float("nan")})  # literal NaN
    res = api.post(
        "/api/experiments", content=body, headers={**researcher, "Content-Type": "application/json"}
    )
    assert res.status_code == 422
    assert res.json()["fields"] == {"commissionRate": "Sayı olmalı"}


def test_costs_have_one_source(api: TestClient, researcher: Headers) -> None:
    exp = _create(api, researcher, commissionRate=0.000123456, slippageBps=1.239)
    assert (exp["commissionRate"], exp["slippageBps"]) == (0.00012, 1.24)
    text = api.get(f"/api/experiments/{exp['id']}/export.yaml", headers=researcher).text
    assert yaml.safe_load(text)["execution"] == {"commission_rate": 0.00012, "slippage_bps": 1.24}


def test_integral_float_seed_is_accepted_like_js(api: TestClient, researcher: Headers) -> None:
    assert _create(api, researcher, seed=5.0)["seed"] == 5


def test_live_mode_may_be_open_ended(api: TestClient, researcher: Headers) -> None:
    exp = _create(api, researcher, mode="live", startDate="2026-10-01", endDate=None)
    assert exp["endDate"] is None


# ---------------------------------------------------------------- sealed test window


@pytest.mark.parametrize(
    ("start", "end", "field"),
    [
        ("2026-03-01", "2026-04-15", "endDate"),  # runs into the window
        ("2026-04-01", "2026-09-30", "startDate"),  # the window itself
        ("2026-09-30", "2026-12-31", "startDate"),  # starts on its last day
        ("2025-01-01", "2027-01-01", "endDate"),  # spans it
        ("2025-10-01", "2026-04-01", "endDate"),  # ends on its first day
    ],
)
def test_period_touching_test_window_is_refused(
    api: TestClient, researcher: Headers, db_session: Session, start: str, end: str, field: str
) -> None:
    res = api.post(
        "/api/experiments", json={**CONFIG, "startDate": start, "endDate": end}, headers=researcher
    )
    assert res.status_code == 422
    assert res.json()["fields"] == {field: SEALED}
    assert db_session.scalar(select(Experiment)) is None


def test_open_ended_live_run_before_the_window_is_refused(
    api: TestClient, researcher: Headers
) -> None:
    res = api.post(
        "/api/experiments",
        json={**CONFIG, "mode": "live", "startDate": "2026-01-01", "endDate": None},
        headers=researcher,
    )
    assert res.status_code == 422
    assert res.json()["fields"] == {"startDate": SEALED}


def test_overlap_rule_matches_frontend() -> None:
    # The same three cases as frontend/src/lib/schemas.test.ts.
    assert not overlaps_test_window(date(2025, 10, 1), date(2026, 3, 31))
    assert overlaps_test_window(date(2026, 3, 1), date(2026, 4, 15))
    assert overlaps_test_window(date(2026, 1, 1), None)
    assert not overlaps_test_window(date(2026, 10, 1), None)


# ---------------------------------------------------------------- edit and delete


def test_patch_merges_and_revalidates(api: TestClient, researcher: Headers) -> None:
    exp = _create(api, researcher)
    url = f"/api/experiments/{exp['id']}"
    res = api.patch(
        url, json={"seed": 9, "agentIds": ["ma-cross", "ppo", "llm-sentiment"]}, headers=researcher
    )
    assert res.status_code == 200, res.text
    assert _config(res.json()) == {
        **CONFIG,
        "seed": 9,
        "agentIds": ["ma-cross", "ppo", "llm-sentiment"],
        "slippageBps": 5.0,
    }
    # The merged configuration is checked: this end date is now before the start.
    bad = api.patch(url, json={"endDate": "2025-09-01"}, headers=researcher)
    assert bad.status_code == 422
    assert "endDate" in bad.json()["fields"]
    sealed = api.patch(url, json={"endDate": "2026-06-01"}, headers=researcher)
    assert sealed.json()["fields"] == {"endDate": SEALED}
    unknown = api.patch(url, json={"status": "completed"}, headers=researcher)
    assert unknown.status_code == 422
    assert unknown.json()["fields"] == {"status": "Bilinmeyen alan."}
    assert api.get(url, headers=researcher).json()["seed"] == 9


def test_patch_only_drafts(api: TestClient, researcher: Headers, db_session: Session) -> None:
    exp = _create(api, researcher)
    _set_status(db_session, exp["id"], ExperimentStatus.COMPLETED)
    res = api.patch(f"/api/experiments/{exp['id']}", json={"seed": 3}, headers=researcher)
    assert res.status_code == 409


@pytest.mark.parametrize(
    ("st", "code"),
    [
        (ExperimentStatus.DRAFT, 204),
        (ExperimentStatus.COMPLETED, 204),
        (ExperimentStatus.FAILED, 204),
        (ExperimentStatus.QUEUED, 409),
        (ExperimentStatus.RUNNING, 409),
        (ExperimentStatus.PAUSED, 409),
    ],
)
def test_delete_by_status(
    api: TestClient, researcher: Headers, db_session: Session, st: ExperimentStatus, code: int
) -> None:
    exp = _create(api, researcher)
    _set_status(db_session, exp["id"], st)
    res = api.delete(f"/api/experiments/{exp['id']}", headers=researcher)
    assert res.status_code == code
    after = api.get(f"/api/experiments/{exp['id']}", headers=researcher).status_code
    assert after == (404 if code == 204 else 200)
    if code == 204:
        assert res.content == b""
        assert db_session.scalars(select(ExperimentAgent)).all() == []


# ---------------------------------------------------------------- YAML


def test_yaml_round_trip(api: TestClient, researcher: Headers) -> None:
    exp = _create(api, researcher, name="Ad: 'tırnaklı' \"çift\" # yorum değil")
    res = api.get(f"/api/experiments/{exp['id']}/export.yaml", headers=researcher)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/yaml")
    doc = yaml.safe_load(res.text)
    assert doc["period"] == {
        "start": date(2025, 10, 1),
        "end": date(2026, 3, 31),
    }
    assert doc["agents"] == CONFIG["agentIds"]
    assert doc["llm"] == {"model": "test-model", "prompt_version": PROMPT_VERSION}

    imported = api.post(
        "/api/experiments/import",
        content=res.content,
        headers={**researcher, "Content-Type": "application/yaml"},
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["id"] != exp["id"]
    assert body["status"] == "draft"
    assert _config(body) == _config(exp)


def test_import_stamps_server_versions(api: TestClient, researcher: Headers) -> None:
    text = (
        "name: Eski dosya\nmode: replay\ncondition: C0\n"
        "period: {start: 2025-10-01, end: 2026-03-31}\nassets: [BTC]\n"
        "agents: [buy-hold-btc, ppo]\nseed: 1\n"
        "execution: {commission_rate: 0.001, slippage_bps: 5}\n"
        "llm: {model: eski-model, prompt_version: decision-v0}\n"
    )
    res = api.post("/api/experiments/import", content=text, headers=researcher)
    assert res.status_code == 201, res.text
    assert (res.json()["modelVersion"], res.json()["promptVersion"]) == (
        "test-model",
        PROMPT_VERSION,
    )


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("name: [unclosed", "body"),
        ("- just\n- a list\n", "body"),
        ("name: x\nsurprise: 1\n", "surprise"),
        ("period: {start: 2025-10-01, stop: 2026-01-01}\n", "period.stop"),
        ("period: 5\n", "period"),
        ("execution: {commission_rate: .nan, slippage_bps: 5}\n", "commissionRate"),
        ("!!python/object:os.system {}\n", "body"),  # safe_load refuses arbitrary tags
    ],
)
def test_import_rejects_bad_yaml(
    api: TestClient, researcher: Headers, text: str, field: str
) -> None:
    res = api.post("/api/experiments/import", content=text, headers=researcher)
    assert res.status_code == 422
    assert field in res.json()["fields"]


def test_import_validates_and_seals(api: TestClient, researcher: Headers) -> None:
    missing = api.post("/api/experiments/import", content="name: Ad\n", headers=researcher)
    assert missing.status_code == 422
    assert missing.json()["fields"]["mode"] == "Zorunlu alan."
    # Dates stay text, so they go through the API's own date validation.
    sealed = config_from_yaml(b"period: {start: 2026-04-01, end: 2026-05-01}\n")
    assert sealed["startDate"] == "2026-04-01"
    text = yaml.safe_dump(
        {
            "name": "Test sızıntısı",
            "mode": "replay",
            "condition": "C0",
            "period": {"start": "2026-04-01", "end": "2026-05-01"},
            "assets": ["BTC"],
            "agents": ["buy-hold-btc", "ppo"],
            "seed": 1,
            "execution": {"commission_rate": 0.001, "slippage_bps": 5},
        }
    )
    res = api.post("/api/experiments/import", content=text, headers=researcher)
    assert res.status_code == 422
    assert res.json()["fields"] == {"startDate": SEALED}


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"commissionRate": int("9" * 400)}, "commissionRate"),  # too big for a float
        ({"slippageBps": -int("9" * 400)}, "slippageBps"),
        ({"name": "Ad\u0000sıfır"}, "name"),  # PostgreSQL text cannot hold NUL
    ],
)
def test_hostile_values_are_422_not_500(
    api: TestClient, researcher: Headers, over: dict[str, Any], field: str
) -> None:
    res = api.post("/api/experiments", json={**CONFIG, **over}, headers=researcher)
    assert res.status_code == 422, res.text
    assert field in res.json()["fields"]


def _valid_yaml(**replace: str) -> str:
    """A complete, valid import document; `replace` swaps whole lines by their key."""
    lines = {
        "name": "name: Geçerli belge",
        "mode": "mode: replay",
        "condition": "condition: C0",
        "period": "period: {start: 2025-10-01, end: 2026-03-31}",
        "assets": "assets: [BTC]",
        "agents": "agents: [buy-hold-btc, ma-cross]",
        "seed": "seed: 1",
        "execution": "execution: {commission_rate: 0.001, slippage_bps: 5}",
        "llm": "llm: {model: m, prompt_version: p}",
    }
    return "\n".join({**lines, **replace}.values()) + "\n"


@pytest.mark.parametrize(
    ("replace", "field"),
    [
        ({"period": "period: {start: 2025-02-30, end: 2026-03-31}"}, "startDate"),
        ({"period": "period: {start: 2025-13-01, end: 2026-03-31}"}, "startDate"),
        ({"seed": "seed: " + "7" * 5000}, "seed"),
    ],
)
def test_impossible_yaml_values_are_field_errors(
    api: TestClient, researcher: Headers, replace: dict[str, str], field: str
) -> None:
    res = api.post("/api/experiments/import", content=_valid_yaml(**replace), headers=researcher)
    assert res.status_code == 422, res.text
    assert field in res.json()["fields"]


@pytest.mark.parametrize(
    ("replace", "field"),
    [
        ({"period": "period: {start: 2025-10-01, end: 2026-03-31, stop: 2026-01-01}"},
         "period.stop"),
        ({"execution": "execution: {commission_rate: 0.001, slippage_bps: 5, leverage: 2}"},
         "execution.leverage"),
        ({"llm": "llm: {model: m, prompt_version: p, temperature: 0.7}"}, "llm.temperature"),
    ],
)  # fmt: skip
def test_extra_nested_keys_in_a_valid_document(
    api: TestClient, researcher: Headers, replace: dict[str, str], field: str
) -> None:
    assert (
        api.post("/api/experiments/import", content=_valid_yaml(), headers=researcher).status_code
        == 201
    )
    res = api.post("/api/experiments/import", content=_valid_yaml(**replace), headers=researcher)
    assert res.status_code == 422
    assert res.json()["fields"] == {field: "Bilinmeyen alan."}


@pytest.mark.parametrize("name", ["1e5", "123", "0.5", "null", "true", "2025-10-01"])
def test_number_like_names_round_trip(api: TestClient, researcher: Headers, name: str) -> None:
    exp = _create(api, researcher, name=name)
    text = api.get(f"/api/experiments/{exp['id']}/export.yaml", headers=researcher).text
    back = api.post("/api/experiments/import", content=text, headers=researcher)
    assert back.status_code == 201, back.text
    assert back.json()["name"] == exp["name"]


def test_mock_quoted_number_like_name_imports(api: TestClient, researcher: Headers) -> None:
    text = re.sub(r"^name: .*$", 'name: "1e5"', MOCK_YAML, flags=re.MULTILINE)
    res = api.post("/api/experiments/import", content=text.encode(), headers=researcher)
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "1e5"


def test_deeply_nested_yaml_is_422_not_500(api: TestClient, researcher: Headers) -> None:
    res = api.post("/api/experiments/import", content="[" * 30000, headers=researcher)
    assert res.status_code == 422
    assert "body" in res.json()["fields"]


def test_oversized_import_without_session_is_401(api: TestClient) -> None:
    res = api.post("/api/experiments/import", content="#" * (70 * 1024))
    assert res.status_code == 401


def test_long_names_survive_yaml_without_folding(api: TestClient, researcher: Headers) -> None:
    exp = _create(api, researcher, name="uzun " * 23 + "ad")  # 117 characters
    text = api.get(f"/api/experiments/{exp['id']}/export.yaml", headers=researcher).text
    assert next(line for line in text.splitlines() if line.startswith("name:")).endswith("ad")


# The exact text the MSW mock exports (frontend/src/mocks/yaml.ts `experimentToYaml`).
MOCK_YAML = """# Mindex deney yapılandırması (F2)
name: "Ad 'tırnaklı' \\"çift\\""
mode: replay
condition: C1
period:
  start: 2025-10-01
  end: 2026-03-31
assets: [BTC, ETH]
agents:
  - buy-hold-btc
  - llm-momentum
seed: 2
execution:
  commission_rate: 0.00001
  slippage_bps: 5
llm:
  model: qwen3.5-9b-q4_k_m
  prompt_version: decision-v1
"""


def test_mock_yaml_imports_into_the_backend(api: TestClient, researcher: Headers) -> None:
    res = api.post("/api/experiments/import", content=MOCK_YAML.encode(), headers=researcher)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Ad 'tırnaklı' \"çift\""
    assert body["agentIds"] == ["buy-hold-btc", "llm-momentum"]
    assert (body["commissionRate"], body["slippageBps"]) == (0.00001, 5.0)


# ---------------------------------------------------------------- ownership


def test_only_the_owner_edits_and_deletes(
    api: TestClient, researcher: Headers, viewer: Headers, db_session: Session
) -> None:
    exp = _create(api, researcher)
    url = f"/api/experiments/{exp['id']}"
    other = _login(api, db_session, "baska@mindex.dev", UserRole.RESEARCHER)
    not_owner = {"detail": NOT_OWNER}
    patched = api.patch(url, json={"seed": 3}, headers=other)
    assert (patched.status_code, patched.json()) == (403, not_owner)
    deleted = api.delete(url, headers=other)
    assert (deleted.status_code, deleted.json()) == (403, not_owner)
    assert api.get(url, headers=other).json() == exp  # reading stays open to everyone
    assert api.get(url, headers=viewer).status_code == 200
    assert api.patch(url, json={"seed": 3}, headers=researcher).status_code == 200


def test_import_size_limit(api: TestClient, researcher: Headers) -> None:
    res = api.post("/api/experiments/import", content="#" * (64 * 1024 + 1), headers=researcher)
    assert res.status_code == 413


# ---------------------------------------------------------------- roles (F1 #7)


def test_viewer_reads_but_cannot_write(
    api: TestClient, researcher: Headers, viewer: Headers
) -> None:
    exp = _create(api, researcher)
    url = f"/api/experiments/{exp['id']}"
    forbidden = {"detail": "Bu işlem için yetkiniz yok."}
    writes = [
        api.post("/api/experiments", json=CONFIG, headers=viewer),
        api.patch(url, json={"seed": 3}, headers=viewer),
        api.delete(url, headers=viewer),
        api.post("/api/experiments/import", content="name: x\n", headers=viewer),
    ]
    for res in writes:
        assert res.status_code == 403
        assert res.json() == forbidden
    assert api.get(url, headers=viewer).json() == exp  # nothing changed
    assert api.get(f"{url}/export.yaml", headers=viewer).status_code == 200
    assert api.get("/api/experiments", headers=viewer).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/experiments"),
        ("POST", "/api/experiments"),
        ("GET", "/api/experiments/x"),
        ("PATCH", "/api/experiments/x"),
        ("DELETE", "/api/experiments/x"),
        ("GET", "/api/experiments/x/export.yaml"),
        ("POST", "/api/experiments/import"),
    ],
)
def test_experiment_routes_need_a_session(api: TestClient, method: str, path: str) -> None:
    assert api.request(method, path).status_code == 401


def test_experiment_routes_are_in_openapi() -> None:
    paths = TestClient(create_app()).get("/api/openapi.json").json()["paths"]
    assert {
        "/api/agents",
        "/api/experiments",
        "/api/experiments/import",
        "/api/experiments/{experiment_id}",
        "/api/experiments/{experiment_id}/export.yaml",
    } <= set(paths)


@pytest.mark.parametrize(
    "replace",
    [
        {"period": "period: {start: !!timestamp abc, end: 2026-03-31}"},  # AttributeError
        {"seed": "seed: !!bool foo"},  # KeyError
        {"period": "period: {start: !!timestamp 2025-02-30, end: 2026-03-31}"},  # ValueError
        {"seed": "seed: !!float foo"},  # ValueError
    ],
)
def test_yaml_constructor_failures_are_422(
    api: TestClient, researcher: Headers, replace: dict[str, str]
) -> None:
    """Whatever a tag's constructor raises, the loading stage answers 422 (never 500)."""
    res = api.post("/api/experiments/import", content=_valid_yaml(**replace), headers=researcher)
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == "YAML okunamadı."
    assert "body" in res.json()["fields"]
