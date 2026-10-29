"""Generated models: no drift, spec examples parse, unknown values never raise."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, RootModel

import vaquill.types as types
from vaquill import ResponseModel, VaquillModel

from .spec import OPS, SPEC, Op, sample

ROOT = Path(__file__).resolve().parent.parent
WITH_EXAMPLE = [o for o in OPS if o.example is not None and o.response is not None]


@pytest.mark.parametrize("script", ["gen_models.py", "gen_async.py"])
def test_generated_files_have_not_drifted(script: str) -> None:
    """Regenerates into a temp dir and compares with the committed files."""
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def model_of(op: Op) -> type[BaseModel]:
    assert op.response is not None
    return getattr(types, op.response["$ref"].rsplit("/", 1)[-1])


@pytest.mark.parametrize("op", WITH_EXAMPLE, ids=lambda o: o.op_id)
def test_response_models_parse_their_spec_example(op: Op) -> None:
    parsed = model_of(op).model_validate(op.example)
    assert isinstance(parsed, ResponseModel)
    example: Any = op.example
    if isinstance(example, dict) and "creditsConsumed" in example:
        assert parsed.credits_consumed == example["creditsConsumed"]


def test_component_examples_parse() -> None:
    parsed = 0
    for name, schema in SPEC["components"]["schemas"].items():
        for example in schema.get("examples", []) + (
            [schema["example"]] if "example" in schema else []
        ):
            getattr(types, name).model_validate(example)
            parsed += 1
    assert parsed >= 1


@pytest.mark.parametrize("name", sorted(SPEC["components"]["schemas"]))
def test_every_schema_parses_a_minimal_valid_instance(name: str) -> None:
    schema: dict[str, Any] = {"$ref": f"#/components/schemas/{name}"}
    model = getattr(types, name, None)
    if isinstance(model, type) and issubclass(model, BaseModel):
        model.model_validate(sample(schema))


def test_every_model_is_a_vaquill_model() -> None:
    models = [getattr(types, n) for n in types.__all__]
    for m in models:
        if isinstance(m, type) and issubclass(m, BaseModel) and m is not BaseModel:
            assert issubclass(m, VaquillModel | RootModel), m.__name__


def test_unknown_enum_values_and_extra_members_never_raise() -> None:
    known = types.ApiCreditCostResponse.model_validate(
        {
            "category": "statutes",
            "credits": 1,
            "description": "d",
            "endpoint": "/e",
            "operation": "o",
            "usdCost": 0.01,
        }
    )
    assert known.category is types.ApiCreditCostResponseCategory.statutes
    new = types.ApiCreditCostResponse.model_validate(
        {
            "category": "brand_new",
            "credits": 1,
            "description": "d",
            "endpoint": "/e",
            "operation": "o",
            "usdCost": 0.01,
            "futureField": 1,
        }
    )
    assert new.category == "brand_new"
    assert new.model_extra == {"futureField": 1}


def test_corpus_type_is_the_shared_enum() -> None:
    assert issubclass(types.CorpusType, str)
    assert {"STATE", "REGULATION"} <= {m.value for m in types.CorpusType}
    holders = [
        n
        for n in types.__all__
        if "CorpusType"
        in str(getattr(getattr(types, n), "model_fields", {}).get("corpus_type", ""))
    ]
    assert holders, "no model references the shared CorpusType"
