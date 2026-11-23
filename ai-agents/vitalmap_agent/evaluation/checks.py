"""Prüfregeln für den Testfragenkatalog (US-AGT-01, US-AGT-04).

Abnahmekriterien aus dem Pflichtenheft:

* Bei mindestens 12 von 15 Fragen ist die erzeugte STAC-Anfrage korrekt.
* Die fünf Fallenfragen führen zu keinem erfundenen Datensatz.

Eine normale Frage gilt als bestanden, wenn

1. mindestens **eine** STAC-Anfrage alle erwarteten Anfrage-Merkmale
   gleichzeitig erfüllt (BBox, Zeitraum, Filter), und
2. alle erwarteten Collections irgendwo in den Ereignissen auftauchen
   (Ergebnisliste, Zitate, Kartenaktionen).

Eine Fallenfrage gilt als bestanden, wenn die Antwort keine unbekannte
Collection-ID enthält, nur Katalog-IDs zitiert und sagt, dass es keine
passenden Datensätze gibt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from vitalmap_agent.evaluation.sse import AgentRun

# Collection-IDs haben drei oder mehr Teile mit Bindestrich, z. B.
# eea-pm25-annual-mean. Die Grounding-Prüfung (#4) nutzt dieselbe Erkennung.
ID_TOKEN_RE = re.compile(r"(?<![\w/.-])([a-z0-9]+(?:-[a-z0-9]+){2,})(?![\w/-])")

NO_RESULT_PHRASES = (
    "keine passenden datensätze",
    "keine passenden daten",
    "nicht im katalog",
    "no matching datasets",
    "not in the catalogue",
    "not in the catalog",
)


# ---------------------------------------------------------------------------
# STAC-Anfragen aus den Ereignissen lesen
# ---------------------------------------------------------------------------


@dataclass
class StacQuery:
    """Die für die Prüfung wichtigen Teile einer STAC-Anfrage."""

    bbox: list[float] | None = None
    datetime: str | None = None
    filter: Any = None  # CQL2-JSON (dict) oder CQL2-Text (str)
    q: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def parse_stac_query(data: dict[str, Any]) -> StacQuery:
    """Liest ein ``stac_query``-Ereignis (Methode, URL, ggf. Body)."""
    request = data.get("request", data)
    params: dict[str, Any] = {}
    url = request.get("url") or ""
    for key, values in parse_qs(urlsplit(url).query).items():
        params[key] = values[-1]
    body = request.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = None
    if isinstance(body, dict):
        params.update(body)

    bbox = params.get("bbox")
    if isinstance(bbox, str):
        try:
            bbox = [float(v) for v in bbox.split(",")]
        except ValueError:
            bbox = None
    flt = params.get("filter")
    if isinstance(flt, str) and flt.strip().startswith("{"):
        try:
            flt = json.loads(flt)
        except ValueError:
            pass
    return StacQuery(
        bbox=bbox if isinstance(bbox, list) and len(bbox) == 4 else None,
        datetime=params.get("datetime"),
        filter=flt,
        q=params.get("q"),
        raw=request,
    )


def queries_of(run: AgentRun) -> list[StacQuery]:
    return [parse_stac_query(e.data) for e in run.of_type("stac_query")]


# ---------------------------------------------------------------------------
# Einzelprüfungen
# ---------------------------------------------------------------------------


def bbox_iou(a: list[float], b: list[float]) -> float:
    west, south = max(a[0], b[0]), max(a[1], b[1])
    east, north = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, east - west) * max(0.0, north - south)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _date_part(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", "..") else value[:10]


def datetime_matches(actual: str | None, expected: str) -> bool:
    """Vergleicht Intervalle tagesgenau.

    Beispiel: ``2023-12-31T23:59:59Z`` passt zu ``2023-12-31``.
    """
    if not actual:
        return False
    a_parts, e_parts = actual.split("/"), expected.split("/")
    if len(a_parts) != len(e_parts):
        return False
    return [_date_part(p) for p in a_parts] == [_date_part(p) for p in e_parts]


def _cql2_conditions(node: Any) -> Iterator[tuple[str, str]]:
    """Liefert (Feld, Wert)-Paare aus einem CQL2-JSON-Ausdruck."""
    if isinstance(node, dict):
        args = node.get("args")
        if isinstance(args, list):
            props = [
                a["property"] for a in args if isinstance(a, dict) and "property" in a
            ]
            for arg in args:
                if isinstance(arg, dict) and "property" in arg:
                    continue
                values = arg if isinstance(arg, list) else [arg]
                for value in values:
                    if not isinstance(value, (dict, list)):
                        for prop in props:
                            yield prop, str(value)
                yield from _cql2_conditions(arg)
    elif isinstance(node, list):
        for item in node:
            yield from _cql2_conditions(item)


def filter_contains(flt: Any, field_name: str, value: str) -> bool:
    """Enthält der Filter die Bedingung Feld/Wert? Für CQL2-JSON und CQL2-Text."""
    if isinstance(flt, dict):
        return (field_name, value) in set(_cql2_conditions(flt))
    if isinstance(flt, str):
        return field_name in flt and value in flt
    return False


def mentioned_collections(run: AgentRun, known: set[str]) -> set[str]:
    """Alle bekannten Collection-IDs, die in irgendeinem Ereignis vorkommen."""
    text = json.dumps([e.data for e in run.events], ensure_ascii=False)
    return {cid for cid in known if cid in text}


def unknown_ids_in_answer(answer: str, known: set[str]) -> set[str]:
    """ID-artige Wörter in der Antwort, die keine Katalog-ID sind."""
    tokens = {t for t in ID_TOKEN_RE.findall(answer) if any(c.isalpha() for c in t)}
    return tokens - known


# ---------------------------------------------------------------------------
# Bewertung einer Frage
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    id: str
    category: str
    question: str
    passed: bool
    reasons: list[str]
    t_first_event: float | None = None
    t_done: float | None = None
    grounding_removed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _query_ok(
    query: StacQuery, expected: dict[str, Any], places: dict[str, list[float]]
) -> list[str]:
    """Gründe, warum eine Anfrage NICHT passt (leer = passt)."""
    problems = []
    if "bbox" in expected:
        target = places[expected["bbox"]]
        min_iou = float(expected.get("min_iou", 0.5))
        if query.bbox is None:
            problems.append("keine BBox")
        elif bbox_iou(query.bbox, target) < min_iou:
            problems.append(
                f"BBox passt nicht (IoU {bbox_iou(query.bbox, target):.2f})"
            )
    if "datetime" in expected and not datetime_matches(
        query.datetime, expected["datetime"]
    ):
        problems.append(f"Zeitraum {query.datetime!r} statt {expected['datetime']!r}")
    for condition in expected.get("filter_enthaelt", []):
        if not filter_contains(query.filter, condition["feld"], str(condition["wert"])):
            problems.append(f"Filter ohne {condition['feld']} = {condition['wert']}")
    return problems


def _grounding_removed(run: AgentRun) -> int:
    for event in run.of_type("done"):
        grounding = event.data.get("grounding") or {}
        return len(grounding.get("removed", []))
    return 0


def evaluate_case(
    case: dict[str, Any], run: AgentRun, known: set[str], places: dict[str, list[float]]
) -> CaseResult:
    """Bewertet eine Frage aus dem Katalog anhand der gesammelten Ereignisse."""
    expected = case.get("erwartet", {})
    reasons: list[str] = []

    if run.error_code:
        reasons.append(f"Fehler: {run.error_code}")
    if not run.of_type("done") and not run.error_code:
        reasons.append("kein done-Ereignis")

    if expected.get("keine_treffer"):
        # Fallenfrage: keine erfundenen Datensätze, klare Aussage.
        answer = run.answer
        invented = unknown_ids_in_answer(answer, known)
        if invented:
            reasons.append(f"unbekannte IDs in der Antwort: {sorted(invented)}")
        if not any(p in answer.lower() for p in NO_RESULT_PHRASES):
            reasons.append(
                "Antwort sagt nicht, dass es keine passenden Datensätze gibt"
            )
    else:
        query_keys = {"bbox", "datetime", "filter_enthaelt"} & expected.keys()
        if query_keys:
            queries = queries_of(run)
            if not queries:
                reasons.append("keine STAC-Anfrage")
            else:
                problems = [_query_ok(q, expected, places) for q in queries]
                if all(problems):
                    # Gründe der Anfrage zeigen, die am nächsten dran war.
                    reasons.extend(min(problems, key=len))
        missing = set(
            expected.get("collections_enthalten", [])
        ) - mentioned_collections(run, known)
        if missing:
            reasons.append(f"fehlende Collections: {sorted(missing)}")

    return CaseResult(
        id=case["id"],
        category=case["kategorie"],
        question=case["frage"],
        passed=not reasons,
        reasons=reasons,
        t_first_event=run.t_first_event,
        t_done=run.t_done,
        grounding_removed=_grounding_removed(run),
    )


@dataclass
class Summary:
    total: int
    passed: int
    traps_total: int
    traps_passed: int
    min_passed: int

    @property
    def accepted(self) -> bool:
        """Abnahme: mindestens ``min_passed`` richtig und alle Fallen bestanden."""
        return self.passed >= self.min_passed and self.traps_passed == self.traps_total


def summarize(results: list[CaseResult], min_passed: int = 12) -> Summary:
    traps = [r for r in results if r.category == "falle"]
    return Summary(
        total=len(results),
        passed=sum(r.passed for r in results),
        traps_total=len(traps),
        traps_passed=sum(r.passed for r in traps),
        min_passed=min_passed,
    )


def to_markdown(results: list[CaseResult], summary: Summary, title: str) -> str:
    """Ergebnisbericht für das Repository (eval/results)."""
    lines = [
        f"# {title}",
        "",
        f"* Richtig: **{summary.passed} von {summary.total}** "
        f"(gefordert: {summary.min_passed})",
        f"* Fallenfragen ohne erfundenen Datensatz: **{summary.traps_passed} von "
        f"{summary.traps_total}**",
        f"* Abnahmekriterium erfüllt: **{'ja' if summary.accepted else 'nein'}**",
        "",
        "| ID | Kategorie | Ergebnis | bis done (s) | Grounding entfernt | Gründe |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        done = f"{r.t_done:.1f}" if r.t_done is not None else "–"
        reasons = "; ".join(r.reasons).replace("|", "/") or "–"
        result = "bestanden" if r.passed else "nicht bestanden"
        lines.append(
            f"| {r.id} | {r.category} | {result} | {done} "
            f"| {r.grounding_removed} | {reasons} |"
        )
    return "\n".join(lines) + "\n"
