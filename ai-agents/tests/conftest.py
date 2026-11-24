"""Gemeinsame Test-Hilfen für den Agenten.

Die JSON Schemas der Schnittstelle Agent ↔ Web-App liegen in
``schemas/interfaces/`` im Wurzelverzeichnis des Repositorys (Issue #2).
Fehlen sie, z. B. auf einem Branch vor deren Merge, werden die Schema-Tests
übersprungen statt fehlzuschlagen.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "interfaces"


@pytest.fixture
def interface_validator() -> Callable[[str], Any]:
    """Liefert eine Funktion, die zu einem Schemanamen einen Validator baut.

    Beispiel: ``interface_validator("sse-events").validate(event)``.
    Relative Verweise wie ``./layer-spec.schema.json`` werden über die
    ``$id`` der Schemas aufgelöst.
    """
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    if not SCHEMA_DIR.is_dir():
        pytest.skip("schemas/interfaces fehlt (Issue #2 noch nicht gemergt)")

    schemas = {
        path.name.removesuffix(".schema.json"): json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in SCHEMA_DIR.glob("*.schema.json")
    }
    registry = referencing.Registry().with_resources(
        (schema["$id"], referencing.Resource.from_contents(schema))
        for schema in schemas.values()
        if "$id" in schema
    )

    def make(name: str) -> Any:
        if name not in schemas:
            pytest.skip(f"{name}.schema.json fehlt in schemas/interfaces")
        return jsonschema.Draft202012Validator(schemas[name], registry=registry)

    return make
