"""Kleiner Demo-Katalog mit STAC Collection Search, nur für Vorführung und Tests.

Ersetzt **nicht** den echten Katalog (stac-fastapi-pgstac aus ``docker/``),
sondern erlaubt, den Agenten ohne Docker zu zeigen. Er liefert die sechs
Beispieldatensätze aus ``demo/collections/`` und versteht die Parameter, die
der Agent nutzt: ``q``, ``bbox``, ``datetime``, ``limit`` und einfache
CQL2-JSON-Filter (``and``, ``or``, ``=``, ``in``, ``a_contains``).

Starten (im Ordner ``ai-agents/``)::

    uvicorn demo.stac_demo:app --port 8081
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

COLLECTIONS_DIR = Path(__file__).resolve().parent / "collections"


def load_collections() -> dict[str, dict[str, Any]]:
    collections = {}
    for path in sorted(COLLECTIONS_DIR.glob("*.json")):
        collection = json.loads(path.read_text(encoding="utf-8"))
        collections[collection["id"]] = collection
    return collections


def _bbox_of(c: dict[str, Any]) -> list[float]:
    return c["extent"]["spatial"]["bbox"][0]


def _interval_of(c: dict[str, Any]) -> tuple[str, str]:
    start, end = c["extent"]["temporal"]["interval"][0]
    return (start or "0000")[:10], (end or "9999")[:10]


def matches_q(c: dict[str, Any], q: str) -> bool:
    """Freitext: mindestens ein Suchwort in Titel, Beschreibung oder Keywords."""
    text = " ".join(
        [c.get("id", ""), c.get("title", ""), c.get("description", "")]
        + c.get("keywords", [])
    ).lower()
    terms = [t for t in q.replace(",", " ").lower().split() if t]
    return any(t in text for t in terms)


def matches_bbox(c: dict[str, Any], bbox: list[float]) -> bool:
    w, s, e, n = _bbox_of(c)
    return bbox[0] <= e and bbox[2] >= w and bbox[1] <= n and bbox[3] >= s


def matches_datetime(c: dict[str, Any], datetime: str) -> bool:
    parts = datetime.split("/")
    start = parts[0] if parts[0] not in ("", "..") else "0000"
    end = parts[-1] if parts[-1] not in ("", "..") else "9999"
    c_start, c_end = _interval_of(c)
    return start[:10] <= c_end and end[:10] >= c_start


def evaluate(node: dict[str, Any], c: dict[str, Any]) -> bool:
    """Wertet einen einfachen CQL2-JSON-Ausdruck gegen eine Collection aus."""
    op = node.get("op", "").lower()
    args = node.get("args", [])
    if op == "and":
        return all(evaluate(a, c) for a in args)
    if op == "or":
        return any(evaluate(a, c) for a in args)
    if op == "not":
        return not evaluate(args[0], c)
    if op in ("=", "in", "a_contains"):
        prop = args[0].get("property") if isinstance(args[0], dict) else None
        if prop is None:
            raise ValueError("erstes Argument muss eine property sein")
        value = c.get(prop)
        if op == "=":
            return value == args[1]
        if op == "in":
            return value in args[1]
        wanted = args[1] if isinstance(args[1], list) else [args[1]]
        return isinstance(value, list) and all(w in value for w in wanted)
    raise ValueError(f"Operator {op!r} wird im Demo-Katalog nicht unterstützt")


app = FastAPI(title="VitalMap Demo-Katalog")
CATALOG = load_collections()


@app.get("/")
def landing() -> dict[str, Any]:
    return {
        "type": "Catalog",
        "id": "vitalmap-demo",
        "description": "Demo-Katalog (Stellvertreter für stac-fastapi-pgstac)",
        "stac_version": "1.1.0",
        "links": [],
    }


@app.get("/collections")
def search(
    q: str | None = None,
    bbox: str | None = None,
    datetime: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    filter: str | None = None,  # noqa: A002 – Name aus der STAC API
    filter_lang: str | None = Query(None, alias="filter-lang"),
) -> dict[str, Any]:
    hits = list(CATALOG.values())
    try:
        if q:
            hits = [c for c in hits if matches_q(c, q)]
        if bbox:
            box = [float(v) for v in bbox.split(",")]
            if len(box) != 4:
                raise ValueError("bbox braucht 4 Zahlen")
            hits = [c for c in hits if matches_bbox(c, box)]
        if datetime:
            hits = [c for c in hits if matches_datetime(c, datetime)]
        if filter:
            if filter_lang not in (None, "cql2-json"):
                raise ValueError("Demo-Katalog versteht nur cql2-json")
            expression = json.loads(filter)
            hits = [c for c in hits if evaluate(expression, c)]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "collections": hits[:limit],
        "links": [],
        "numberMatched": len(hits),
        "numberReturned": min(len(hits), limit),
    }


@app.get("/collections/{collection_id}")
def get_collection(collection_id: str) -> dict[str, Any]:
    if collection_id not in CATALOG:
        raise HTTPException(status_code=404, detail="Collection nicht gefunden")
    return CATALOG[collection_id]
