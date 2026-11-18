"""OpenAPI → TypeScript (`mindex openapi`): the committed frontend types match the API."""

from pathlib import Path

import pytest

from mindex import cli
from mindex.api.app import create_app
from mindex.api.typescript import declarations, generate, operations, ts_type

GENERATED = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "generated.ts"


def test_committed_types_match_the_api() -> None:
    # Same check as CI's `git diff --exit-code`; fix with `npm run gen:api`.
    assert GENERATED.read_text(encoding="utf-8") == generate(create_app())


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"$ref": "#/components/schemas/Asset"}, "Asset"),
        ({"type": "string", "format": "date"}, "string"),
        ({"type": "integer"}, "number"),
        ({"type": "boolean"}, "boolean"),
        ({"type": "null"}, "null"),
        ({"const": "ok"}, "'ok'"),
        ({"enum": ["a", "it's"]}, "'a' | \"it's\""),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string | null"),
        ({"type": "array", "items": {"anyOf": [{"type": "number"}, {"type": "null"}]}},
         "(number | null)[]"),
        ({"type": "object", "additionalProperties": {"type": "string"}}, "Record<string, string>"),
        (
            {
                "type": "object",
                "additionalProperties": {"type": "number"},
                "propertyNames": {"$ref": "#/components/schemas/Asset"},
            },
            "Partial<Record<Asset, number>>",
        ),
        ({"type": "object"}, "Record<string, unknown>"),
        ({}, "unknown"),
    ],
)  # fmt: skip
def test_schema_nodes(schema: dict[str, object], expected: str) -> None:
    assert ts_type(schema) == expected


def test_objects_mark_optional_and_quote_odd_keys() -> None:
    out = declarations(
        {
            "components": {
                "schemas": {
                    "Thing-Input": {
                        "type": "object",
                        "properties": {"a": {"type": "string"}, "b-c": {"type": "integer"}},
                        "required": ["a"],
                    }
                }
            }
        }
    )
    assert 'export interface Thing_Input {\n  a: string\n  "b-c"?: number\n}\n' in out


def test_cli_writes_ts_and_json(tmp_path: Path) -> None:
    ts, js = tmp_path / "generated.ts", tmp_path / "openapi.json"
    cli.main(["openapi", "--ts", str(ts), "--json", str(js)])
    assert ts.read_text(encoding="utf-8") == generate(create_app())
    assert '"openapi"' in js.read_text(encoding="utf-8")


def test_operations_map_responses_and_bodies() -> None:
    spec = create_app().openapi()
    responses, bodies = operations(spec)
    assert responses["GET /api/experiments"] == "ExperimentOut[]"
    assert responses["POST /api/experiments/{experiment_id}/start"] == "ExperimentOut"
    assert "DELETE /api/experiments/{experiment_id}" not in responses  # 204, no body
    assert bodies["PATCH /api/experiments/{experiment_id}"] == "ExperimentUpdate"
    assert "POST /api/experiments/import" not in bodies  # YAML, not JSON
    # Every 4xx is documented as the `{detail, fields?}` envelope.
    patch = spec["paths"]["/api/experiments/{experiment_id}"]["patch"]["responses"]
    assert patch["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiErrorBody"
    }
