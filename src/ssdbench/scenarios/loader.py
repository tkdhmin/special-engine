"""Scenario YAML loader with JSON Schema validation."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field


class Workload(BaseModel):
    pattern: str
    block_size: str
    io_depth: int
    num_jobs: int
    rw_mix_read: int | None = None


class Runtime(BaseModel):
    duration_sec: int
    ramp_sec: int = 0


class Engine(BaseModel):
    name: str
    direct: bool


class Scenario(BaseModel):
    name: str
    version: int
    description: str = ""
    workload: Workload
    runtime: Runtime
    engine: Engine

    # keep the original YAML text so we can save it verbatim inside a run directory
    raw_yaml: str = Field(default="", exclude=True)


class ScenarioError(Exception):
    """Raised for scenario loading or validation failures."""


def _load_schema() -> dict[str, Any]:
    schema_text = resources.files("ssdbench.scenarios").joinpath("schema.json").read_text()
    data: dict[str, Any] = json.loads(schema_text)
    return data


_VALIDATOR = Draft202012Validator(_load_schema())


def _validate(data: dict[str, Any]) -> None:
    errors = sorted(_VALIDATOR.iter_errors(data), key=lambda e: e.path)
    if not errors:
        return
    messages = []
    for err in errors:
        location = ".".join(str(p) for p in err.path) or "<root>"
        messages.append(f"  at {location}: {err.message}")
    raise ScenarioError("scenario failed schema validation:\n" + "\n".join(messages))


def _parse(raw_yaml: str, source: str) -> Scenario:
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise ScenarioError(f"could not parse {source}: {e}") from e
    if not isinstance(data, dict):
        raise ScenarioError(f"{source} does not contain a YAML mapping at the top level")
    _validate(data)
    scenario = Scenario(**data)
    scenario.raw_yaml = raw_yaml
    return scenario


def load_scenario_from_file(path: Path) -> Scenario:
    """Load a scenario from an arbitrary YAML file on disk."""
    try:
        raw = path.read_text()
    except OSError as e:
        raise ScenarioError(f"could not read {path}: {e}") from e
    return _parse(raw, str(path))


def load_scenario(name: str) -> Scenario:
    """Load a scenario from the built in catalog by name."""
    catalog = resources.files("ssdbench.scenarios.catalog")
    candidate = catalog.joinpath(f"{name}.yaml")
    if not candidate.is_file():
        available = ", ".join(sorted(list_catalog()))
        raise ScenarioError(
            f"unknown scenario '{name}'. available scenarios: {available}"
        )
    return _parse(candidate.read_text(), f"catalog:{name}")


def list_catalog() -> list[str]:
    """Return the names of built in catalog scenarios."""
    catalog = resources.files("ssdbench.scenarios.catalog")
    names = []
    for entry in catalog.iterdir():
        if entry.name.endswith(".yaml"):
            names.append(entry.name[: -len(".yaml")])
    return sorted(names)
