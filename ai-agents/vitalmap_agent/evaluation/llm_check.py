"""Prüfregeln für den Verbindungs- und Tool-Calling-Test mit uniGPT (Risiko R3).

Der Test gibt dem Modell ein Tool ``search_collections`` mit dem Schema, das
der Agent später nutzt, und stellt die Beispielfrage aus US-AGT-01. Bestanden
ist er, wenn das Modell das Tool mit gültigem JSON aufruft und darin eine BBox
für NRW und den Zeitraum 2020 bis 2023 setzt.
"""

from __future__ import annotations

import json
from typing import Any

QUESTION = "Welche Datensätze zeigen PM2.5 in NRW für 2020–2023?"

SYSTEM_PROMPT = (
    "Du bist der Suchassistent von VitalMap. Suche Datensätze immer mit dem Tool "
    "search_collections. Rechne Ortsnamen selbst in eine BBox in WGS84 um."
)

SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_collections",
        "description": (
            "Durchsucht den STAC-Katalog nach Collections (Collection Search)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Freitext, z. B. PM2.5"},
                "bbox": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[West, Süd, Ost, Nord] in WGS84",
                },
                "datetime": {
                    "type": "string",
                    "description": "Intervall (RFC 3339): 2020-01-01/2023-12-31",
                },
            },
            "required": ["q"],
        },
    },
}

# Grobe Plausibilität für NRW (West, Süd, Ost, Nord).
NRW_BBOX = (5.87, 50.32, 9.47, 52.53)


def _overlaps_nrw(bbox: list[float]) -> bool:
    west, south, east, north = bbox
    return (
        west < NRW_BBOX[2]
        and east > NRW_BBOX[0]
        and south < NRW_BBOX[3]
        and (north > NRW_BBOX[1])
    )


def evaluate_tool_calls(tool_calls: list[Any] | None) -> list[str]:
    """Gründe, warum der Tool-Aufruf nicht passt (leere Liste = bestanden).

    ``tool_calls`` ist die Liste aus ``message.tool_calls`` der OpenAI-API;
    jeder Eintrag hat ``function.name`` und ``function.arguments`` (JSON-Text).
    """
    if not tool_calls:
        return ["kein Tool-Aufruf"]
    call = tool_calls[0]
    function = getattr(call, "function", None) or call.get("function", {})
    name = getattr(function, "name", None) or function.get("name")
    raw = getattr(function, "arguments", None) or function.get("arguments") or ""
    problems = []
    if name != "search_collections":
        problems.append(f"falsches Tool: {name!r}")
    try:
        args = json.loads(raw)
    except ValueError:
        return [*problems, "Argumente sind kein gültiges JSON"]
    bbox = args.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4):
        problems.append("keine BBox mit vier Zahlen")
    elif not all(isinstance(v, (int, float)) for v in bbox) or not _overlaps_nrw(bbox):
        problems.append(f"BBox passt nicht zu NRW: {bbox}")
    dt = str(args.get("datetime") or "")
    if "2020" not in dt or "2023" not in dt:
        problems.append(f"Zeitraum fehlt oder falsch: {dt!r}")
    return problems
