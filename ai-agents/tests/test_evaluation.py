"""Tests für die Auswertung des Testfragenkatalogs (ohne laufenden Agenten).

Die SSE-Ströme sind von Hand gebaut und folgen dem Format aus Issue #2
(``schemas/interfaces/sse-events.schema.json``): status, token, stac_query,
done, error.
"""

import json
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
import respx

from vitalmap_agent.evaluation.catalog import load_catalog
from vitalmap_agent.evaluation.checks import (
    datetime_matches,
    evaluate_case,
    filter_contains,
    parse_stac_query,
    summarize,
    to_markdown,
)
from vitalmap_agent.evaluation.sse import (
    AgentRun,
    SseEvent,
    build_payload,
    parse_sse_lines,
    stream_agent,
)

CATALOG = Path(__file__).resolve().parent.parent / "eval" / "testfragen.yaml"
ONGOING = {
    "op": "and",
    "args": [
        {"op": "=", "args": [{"property": "health:status"}, "onGoing"]},
        {
            "op": "a_contains",
            "args": [{"property": "health:representation_type"}, ["timeSeries"]],
        },
    ],
}
STATUS = ("status", {"message": "Suche im Katalog …"})
TIMEOUT = (
    "error",
    {"type": "agent_error", "code": "TIMEOUT", "message": "…", "retryable": True},
)


def run_with(*events: tuple[str, dict]) -> AgentRun:
    """Baut einen Lauf aus (Typ, Daten)-Paaren; Zeiten steigen um 0,5 s."""
    run = AgentRun(question="test")
    run.events = [
        SseEvent(kind, data, 0.5 * (i + 1)) for i, (kind, data) in enumerate(events)
    ]
    return run


def stac_get(**params) -> tuple[str, dict]:
    """``stac_query``-Ereignis für eine Collection Search per GET."""
    url = "http://stac-api:8080/collections?" + urlencode(params)
    return "stac_query", {"method": "GET", "url": url, "body": None, "collections": []}


def done(answer: str = "…", *citations: str) -> tuple[str, dict]:
    """``done``-Ereignis mit geprüftem Text und Grounding-Bericht."""
    grounding = {"grounded": True, "removed": [], "citations": list(citations)}
    return "done", {"answer": answer, "grounding": grounding}


# -- Schnittstelle (Issue #2) --------------------------------------------------------


def test_anfrage_passt_zum_schema(interface_validator):
    interface_validator("chat-request").validate(build_payload("Frage?", lang="en"))


@pytest.mark.parametrize(
    "event",
    [
        STATUS,
        ("token", {"text": "Hallo"}),
        stac_get(bbox="5.87,50.32,9.46,52.53", datetime="2020-01-01/2023-12-31"),
        done("Gefunden: [[eea-pm25-annual-mean]]", "eea-pm25-annual-mean"),
        TIMEOUT,
    ],
    ids=lambda e: e[0],
)
def test_testereignisse_passen_zum_schema(interface_validator, event):
    kind, data = event
    interface_validator("sse-events").validate({"event": kind, "data": data})


# -- SSE ---------------------------------------------------------------------------


def test_sse_mit_event_zeile_und_nur_data():
    lines = [
        ": keep-alive",
        "event: status",
        'data: {"message": "Suche im Katalog …"}',
        "",
        'data: {"type": "token", "text": "Hallo"}',
        "",
        "event: done",
        "data: {",
        'data:  "answer": "fertig"}',  # mehrzeilige Daten
        "",
    ]
    parsed = list(parse_sse_lines(lines))
    assert [kind for kind, _ in parsed] == ["status", "token", "done"]
    assert parsed[2][1]["answer"] == "fertig"


def test_antwort_bevorzugt_geprueften_text_aus_done():
    run = run_with(("token", {"text": "Roh "}), ("token", {"text": "text"}))
    assert run.answer == "Roh text"
    kind, data = done("Geprüfter Text")
    run.events.append(SseEvent(kind, data, 2.0))
    assert run.answer == "Geprüfter Text"


@pytest.mark.asyncio
@respx.mock
async def test_stream_agent_sammelt_ereignisse_bis_done():
    grounding = '{"grounded": true, "removed": [], "citations": []}'
    body = (
        'event: status\ndata: {"message": "…"}\n\n'
        'event: token\ndata: {"text": "Hi"}\n\n'
        f'event: done\ndata: {{"answer": "Hi", "grounding": {grounding}}}\n\n'
        'event: token\ndata: {"text": "nach done"}\n\n'
    )
    route = respx.post("http://agent.test/api/agent/chat").mock(
        return_value=httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )
    )
    run = await stream_agent("http://agent.test/api/agent/chat", "Frage?")
    assert [e.type for e in run.events] == ["status", "token", "done"]
    assert run.t_first_event is not None and run.t_done is not None
    sent = json.loads(route.calls.last.request.content)
    assert sent["message"] == "Frage?" and sent["session_id"].startswith("eval-")


@pytest.mark.asyncio
@respx.mock
async def test_stream_agent_meldet_verbindungsfehler():
    respx.post("http://agent.test/api/agent/chat").mock(
        side_effect=httpx.ConnectError("weg")
    )
    run = await stream_agent("http://agent.test/api/agent/chat", "Frage?")
    assert run.error_code == "ConnectError"


# -- STAC-Anfragen -----------------------------------------------------------------


def test_get_anfrage_mit_bbox_datetime_und_filter():
    _, data = stac_get(
        bbox="5.87,50.32,9.46,52.53",
        datetime="2020-01-01/2023-12-31",
        filter=json.dumps(ONGOING),
    )
    query = parse_stac_query(data)
    assert query.bbox == [5.87, 50.32, 9.46, 52.53]
    assert query.datetime == "2020-01-01/2023-12-31"
    assert filter_contains(query.filter, "health:status", "onGoing")
    assert filter_contains(query.filter, "health:representation_type", "timeSeries")


def test_post_anfrage_mit_body():
    query = parse_stac_query(
        {
            "method": "POST",
            "url": "http://x/search",
            "body": {"bbox": [1, 2, 3, 4]},
            "collections": [],
        }
    )
    assert query.bbox == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "actual, ok",
    [
        ("2020-01-01/2023-12-31", True),
        ("2020-01-01T00:00:00Z/2023-12-31T23:59:59Z", True),
        ("2020-01-01/2022-12-31", False),
        ("2020-01-01/..", False),
        (None, False),
    ],
)
def test_zeitraum_vergleich(actual, ok):
    assert datetime_matches(actual, "2020-01-01/2023-12-31") is ok


def test_cql2_text_filter():
    text = (
        "health:status = 'onGoing' AND "
        "A_CONTAINS(health:representation_type, ('timeSeries'))"
    )
    assert filter_contains(text, "health:status", "onGoing")
    assert not filter_contains(text, "health:format", "CSV")


# -- Bewertung ---------------------------------------------------------------------

CATALOG_DATA = load_catalog(CATALOG)


def case(case_id: str) -> dict:
    return next(q for q in CATALOG_DATA.questions if q["id"] == case_id)


def evaluate(case_id: str, run: AgentRun):
    return evaluate_case(
        case(case_id), run, CATALOG_DATA.known_ids, CATALOG_DATA.places
    )


def test_k1_bestanden():
    run = run_with(
        STATUS,
        stac_get(
            bbox="5.87,50.32,9.46,52.53", datetime="2020-01-01/2023-12-31", q="PM2.5"
        ),
        done("…", "eea-pm25-annual-mean"),
    )
    assert evaluate("K1", run).passed


def test_k1_bbox_und_zeitraum_muessen_in_derselben_anfrage_stehen():
    run = run_with(
        stac_get(bbox="5.87,50.32,9.46,52.53"),
        stac_get(datetime="2020-01-01/2023-12-31"),
        done("…", "eea-pm25-annual-mean"),
    )
    result = evaluate("K1", run)
    assert not result.passed
    assert any("Zeitraum" in r or "BBox" in r for r in result.reasons)


def test_falsche_bbox_wird_erkannt():
    run = run_with(
        stac_get(bbox="7.47,51.84,7.77,52.06"),  # Münster statt Kreis Steinfurt
        done("…", "osm-hospitals-nrw", "inkar-gp-density-districts"),
    )
    result = evaluate("R1", run)
    assert not result.passed and "BBox passt nicht" in result.reasons[0]


def test_t3_filter_aus_pflichtenheft():
    run = run_with(
        stac_get(filter=json.dumps(ONGOING), **{"filter-lang": "cql2-json"}),
        done("…", "rki-covid19-incidence-districts"),
    )
    assert evaluate("T3", run).passed


def test_fallenfrage_bestanden():
    run = run_with(
        stac_get(q="Masern", bbox="8.97,47.27,13.84,50.56"),
        done("Dazu gibt es keine passenden Datensätze im Katalog."),
    )
    assert evaluate("F1", run).passed


def test_fallenfrage_mit_erfundener_id():
    run = run_with(
        done("Nutzen Sie krebsregister-nrw-2019 – keine passenden Datensätze sonst.")
    )
    result = evaluate("F2", run)
    assert not result.passed
    assert "krebsregister-nrw-2019" in result.reasons[0]


def test_fallenfrage_ohne_klare_aussage():
    run = run_with(done("Vielleicht hilft der Datensatz zur Luftqualität."))
    assert not evaluate("F3", run).passed


def test_fehler_ereignis_laesst_frage_scheitern():
    result = evaluate("T1", run_with(STATUS, TIMEOUT))
    assert not result.passed and "Fehler: TIMEOUT" in result.reasons


# -- Katalog und Bericht -------------------------------------------------------------


def test_katalog_hat_15_fragen_davon_5_fallen():
    assert len(CATALOG_DATA.questions) == 15
    assert sum(q["kategorie"] == "falle" for q in CATALOG_DATA.questions) == 5
    assert CATALOG_DATA.min_passed == 12


def test_kaputter_katalog_wird_abgelehnt(tmp_path):
    broken = CATALOG.read_text(encoding="utf-8").replace(
        "bbox: muenster", "bbox: muenstr"
    )
    path = tmp_path / "kaputt.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(ValueError, match="muenstr"):
        load_catalog(path)


def test_zusammenfassung_und_bericht():
    passed = evaluate("F1", run_with(done("Keine passenden Datensätze.")))
    failed = evaluate("F2", run_with(done("Hier: erfunden-ab-cd")))
    summary = summarize([passed, failed], min_passed=1)
    assert (summary.passed, summary.traps_passed, summary.traps_total) == (1, 1, 2)
    assert not summary.accepted  # eine Falle nicht bestanden
    report = to_markdown([passed, failed], summary, "Test")
    assert "| F2 | falle | nicht bestanden |" in report
