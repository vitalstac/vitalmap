"""Tests für STAC-Tools, LangGraph-Agent und SSE-Endpunkt – ohne Netzwerk und LLM.

Das Sprachmodell ist ein Skript (``ScriptedBackend``), die STAC API ist der
Demo-Katalog aus ``demo/stac_demo.py``, angesprochen über ASGI im Prozess.
"""

import json

import httpx
import pytest

from demo.stac_demo import app as demo_stac_app
from vitalmap_agent.agent import VitalMapAgent, ground_answer
from vitalmap_agent.api import create_app
from vitalmap_agent.evaluation.sse import parse_sse_lines
from vitalmap_agent.resilience import AgentError, ErrorCode
from vitalmap_agent.stac import StacClient

PM25_CALL = {
    "id": "call-1",
    "type": "function",
    "function": {
        "name": "search_collections",
        "arguments": json.dumps(
            {"q": "PM2.5", "bbox": [5.8, 50.3, 9.5, 52.5], "datetime": "2020/2023"}
        ),
    },
}


class ScriptedBackend:
    """Liefert vorgegebene Antworten des Sprachmodells, Zug um Zug."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []

    async def complete(self, messages, tools, on_token):
        self.seen.append(messages)
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        if turn.get("content"):
            for word in turn["content"].split(" "):
                on_token(word + " ")
        return {"role": "assistant", **turn}


def demo_stac() -> StacClient:
    transport = httpx.ASGITransport(app=demo_stac_app)
    return StacClient("http://demo", httpx.AsyncClient(transport=transport))


async def collect(agent, message="Frage?", session="s1"):
    return [e async for e in agent.run(session, message, "de", {})]


# -- STAC-Tools --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_collections_mit_bbox_und_zeitraum():
    stac = demo_stac()
    hits, event = await stac.search_collections(
        q="PM2.5", bbox=[5.8, 50.3, 9.5, 52.5], datetime="2020-01-01/2023-12-31"
    )
    assert [h["id"] for h in hits] == ["eea-pm25-annual-mean"]
    assert "bbox=5.8%2C50.3%2C9.5%2C52.5" in event["url"]
    assert event["collections"][0]["id"] == "eea-pm25-annual-mean"


@pytest.mark.asyncio
async def test_health_filter_wird_als_cql2_json_gesendet():
    stac = demo_stac()
    flt = {"op": "=", "args": [{"property": "health:status"}, "onGoing"]}
    hits, event = await stac.search_collections(filter=flt)
    assert {h["id"] for h in hits} == {
        "rki-covid19-incidence-districts",
        "dwd-hot-days-annual",
    }
    assert "filter-lang=cql2-json" in event["url"]


@pytest.mark.asyncio
async def test_get_collection_liefert_lizenzlink():
    summary, event = await demo_stac().get_collection("eea-pm25-annual-mean")
    assert summary["license"] == "CC-BY-4.0"
    assert any(link["rel"] == "license" for link in summary["links"])
    assert event["url"].endswith("/collections/eea-pm25-annual-mean")


@pytest.mark.asyncio
async def test_ungueltiger_filter_ist_invalid_request():
    with pytest.raises(AgentError) as info:
        await demo_stac().search_collections(filter={"op": "like", "args": []})
    assert info.value.code == ErrorCode.INVALID_REQUEST


# -- Grounding Stufe 1 ---------------------------------------------------------------


def test_grounding_entfernt_erfundene_datensaetze():
    answer = "Siehe [[eea-pm25-annual-mean]] und [[krebsregister-nrw-2019]]."
    checked, report = ground_answer(answer, {"eea-pm25-annual-mean"})
    assert "krebsregister" not in checked and "[nicht im Katalog]" in checked
    assert report == {
        "grounded": False,
        "removed": ["krebsregister-nrw-2019"],
        "citations": ["eea-pm25-annual-mean"],
    }


def test_grounding_ohne_markierungen_bleibt_unveraendert():
    checked, report = ground_answer("Keine passenden Datensätze im Katalog.", set())
    assert report["grounded"] and checked.startswith("Keine passenden")


# -- Agent -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_sucht_und_belegt_die_antwort():
    backend = ScriptedBackend(
        {"content": None, "tool_calls": [PM25_CALL]},
        {"content": "Gefunden: [[eea-pm25-annual-mean]] und [[erfunden-ab-cd]]."},
    )
    events = await collect(VitalMapAgent(backend, demo_stac()))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "done"
    assert "stac_query" in kinds and "token" in kinds
    done = events[-1]["data"]
    assert done["grounding"]["citations"] == ["eea-pm25-annual-mean"]
    assert done["grounding"]["removed"] == ["erfunden-ab-cd"]


@pytest.mark.asyncio
async def test_tool_ergebnis_geht_ans_modell():
    backend = ScriptedBackend(
        {"content": None, "tool_calls": [PM25_CALL]}, {"content": "ok"}
    )
    await collect(VitalMapAgent(backend, demo_stac()))
    tool_message = backend.seen[1][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call-1"
    assert "eea-pm25-annual-mean" in tool_message["content"]


@pytest.mark.asyncio
async def test_folgefrage_kennt_den_verlauf():
    backend = ScriptedBackend({"content": "Erste"}, {"content": "Zweite"})
    agent = VitalMapAgent(backend, demo_stac())
    await collect(agent, "Frage 1", session="gleich")
    await collect(agent, "Frage 2", session="gleich")
    contents = [m.get("content") for m in backend.seen[1]]
    assert "Frage 1" in contents and "Erste" in contents and "Frage 2" in contents


@pytest.mark.asyncio
async def test_kontext_bbox_steht_im_system_prompt():
    backend = ScriptedBackend({"content": "ok"})
    agent = VitalMapAgent(backend, demo_stac())
    context = {"bbox": [7.5, 51.8, 7.8, 52.1], "datetime": None}
    _ = [e async for e in agent.run("s", "Was gibt es hier?", "de", context)]
    assert "[7.5, 51.8, 7.8, 52.1]" in backend.seen[0][0]["content"]


# -- SSE-Endpunkt ----------------------------------------------------------------------


async def post_chat(app, payload):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent") as c:
        response = await c.post("/api/agent/chat", json=payload)
    return response, list(parse_sse_lines(response.text.splitlines()))


REQUEST = {
    "session_id": "t",
    "message": "Welche Datensätze zeigen PM2.5 in NRW?",
    "lang": "de",
    "context": {
        "bbox": [-180, -90, 180, 90],
        "zoom": 0,
        "layers": [],
        "datasets": [],
        "selected": [],
        "filters": {},
        "datetime": None,
    },
}


@pytest.mark.asyncio
async def test_endpunkt_streamt_ereignisse_nach_schema(interface_validator):
    backend = ScriptedBackend(
        {"content": None, "tool_calls": [PM25_CALL]},
        {"content": "Gefunden: [[eea-pm25-annual-mean]]"},
    )
    app = create_app(VitalMapAgent(backend, demo_stac()))
    response, events = await post_chat(app, REQUEST)
    assert response.headers["content-type"].startswith("text/event-stream")
    validator = interface_validator("sse-events")
    for kind, data in events:
        validator.validate({"event": kind, "data": data})
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_endpunkt_meldet_fehler_als_ereignis():
    backend = ScriptedBackend(AgentError(ErrorCode.UPSTREAM_UNAVAILABLE, tool="llm"))
    app = create_app(VitalMapAgent(backend, demo_stac()))
    _, events = await post_chat(app, REQUEST)
    kind, data = events[-1]
    assert kind == "error" and data["code"] == "UPSTREAM_UNAVAILABLE"
    assert data["retryable"] is True


@pytest.mark.asyncio
async def test_leere_frage_wird_abgelehnt():
    app = create_app(VitalMapAgent(ScriptedBackend(), demo_stac()))
    response, _ = await post_chat(app, {**REQUEST, "message": ""})
    assert response.status_code == 422
