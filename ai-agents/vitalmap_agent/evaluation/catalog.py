"""Laden und Plausibilitätsprüfung des Testfragenkatalogs (eval/testfragen.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = {"raeumlich", "zeitlich", "thematisch", "kombiniert", "falle"}


@dataclass
class Catalog:
    questions: list[dict[str, Any]]
    known_ids: set[str]
    places: dict[str, list[float]]
    min_passed: int


def load_catalog(path: str | Path) -> Catalog:
    """Lädt den Katalog und prüft ihn auf Tippfehler, bevor Fragen gestellt werden."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    known = set(data["katalog_ids"])
    places = {k: [float(v) for v in bbox] for k, bbox in data["orte"].items()}
    questions = data["fragen"]

    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("Frage-IDs sind nicht eindeutig.")
    for q in questions:
        if q["kategorie"] not in CATEGORIES:
            raise ValueError(f"{q['id']}: unbekannte Kategorie {q['kategorie']!r}")
        expected = q.get("erwartet") or {}
        if "bbox" in expected and expected["bbox"] not in places:
            raise ValueError(f"{q['id']}: Ort {expected['bbox']!r} fehlt unter 'orte'")
        unknown = set(expected.get("collections_enthalten", [])) - known
        if unknown:
            raise ValueError(f"{q['id']}: unbekannte Collections {sorted(unknown)}")
        if (q["kategorie"] == "falle") != bool(expected.get("keine_treffer")):
            raise ValueError(f"{q['id']}: Fallenfragen brauchen 'keine_treffer: true'")
    return Catalog(questions, known, places, int(data.get("min_bestanden", 12)))
