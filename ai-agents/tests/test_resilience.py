"""Tests für vitalmap_agent.resilience (US-AGT-08, Abschnitt 5.1).

HTTP-Aufrufe werden mit respx gemockt; es gibt keine echten Netzwerkzugriffe.
Die Zeitlimits sind sehr klein gewählt, damit die Tests schnell bleiben.
"""

import asyncio

import httpx
import pytest
import respx

from vitalmap_agent.resilience import (
    AgentError,
    ErrorCode,
    ResilienceSettings,
    call_with_retry,
    remaining_time,
    request_deadline,
)

URL = "http://stac.test/collections"

# Schnelle Einstellungen für Tests: 1 Wiederholung, kaum Wartezeit.
FAST = ResilienceSettings(
    request_timeout_s=5.0, tool_timeout_s=0.5, max_attempts=2, backoff_s=0.01
)


async def _get_json(client: httpx.AsyncClient) -> dict:
    """So sieht ein typischer Tool-Aufruf aus: GET, Status prüfen, JSON lesen."""
    response = await client.get(URL)
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
@respx.mock
async def test_erfolg_beim_ersten_versuch():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as client:
        result = await call_with_retry(
            lambda: _get_json(client), tool="search_collections", settings=FAST
        )
    assert result == {"ok": True}
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_genau_eine_wiederholung_bei_5xx():
    # Erst 503, dann 200: Die Wiederholung soll den Fehler ausgleichen.
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    async with httpx.AsyncClient() as client:
        result = await call_with_retry(
            lambda: _get_json(client), tool="search_collections", settings=FAST
        )
    assert result == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_nach_zweitem_fehler_kommt_agent_error():
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        with pytest.raises(AgentError) as info:
            await call_with_retry(
                lambda: _get_json(client), tool="search_collections", settings=FAST
            )
    # Genau zwei Aufrufe: ein Versuch plus eine Wiederholung, nicht mehr.
    assert route.call_count == 2
    assert info.value.code == ErrorCode.UPSTREAM_UNAVAILABLE
    assert info.value.tool == "search_collections"


@pytest.mark.asyncio
@respx.mock
async def test_4xx_wird_nicht_wiederholt():
    route = respx.get(URL).mock(return_value=httpx.Response(400))
    async with httpx.AsyncClient() as client:
        with pytest.raises(AgentError) as info:
            await call_with_retry(
                lambda: _get_json(client), tool="search_collections", settings=FAST
            )
    assert route.call_count == 1
    assert info.value.code == ErrorCode.INVALID_REQUEST
    assert info.value.retryable is False


@pytest.mark.asyncio
@respx.mock
async def test_429_mit_retry_after_wird_wiederholt():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as client:
        result = await call_with_retry(
            lambda: _get_json(client), tool="geocode", settings=FAST
        )
    assert result == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_netzwerkfehler_wird_wiederholt():
    route = respx.get(URL).mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={})]
    )
    async with httpx.AsyncClient() as client:
        await call_with_retry(lambda: _get_json(client), tool="x", settings=FAST)
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_zeitlimit_je_versuch():
    calls = 0

    async def slow() -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(1.0)  # länger als tool_timeout_s = 0.5

    settings = ResilienceSettings(tool_timeout_s=0.05, max_attempts=2, backoff_s=0)
    with pytest.raises(AgentError) as info:
        await call_with_retry(slow, tool="get_collection", settings=settings)
    assert calls == 2
    assert info.value.code == ErrorCode.UPSTREAM_UNAVAILABLE


@pytest.mark.asyncio
async def test_gesamtfrist_liefert_timeout_event():
    with pytest.raises(AgentError) as info:
        async with request_deadline(0.05):
            await asyncio.sleep(1.0)
    event = info.value.to_event("de")
    assert event["type"] == "agent_error"
    assert event["code"] == "TIMEOUT"
    assert event["retryable"] is True
    assert "60 Sekunden" in event["message"]


@pytest.mark.asyncio
async def test_tool_zeitlimit_wird_durch_gesamtfrist_begrenzt():
    # Das Tool hätte 10 s Zeit, die Anfrage aber nur noch 0.05 s.
    # Dann darf es keine Wiederholung geben, sondern sofort TIMEOUT.
    calls = 0

    async def slow() -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(1.0)

    settings = ResilienceSettings(tool_timeout_s=10, max_attempts=2, backoff_s=0)
    with pytest.raises(AgentError) as info:
        async with request_deadline(0.05):
            await call_with_retry(slow, tool="search_items", settings=settings)
    assert info.value.code == ErrorCode.TIMEOUT
    assert calls == 1


@pytest.mark.asyncio
async def test_remaining_time_nur_innerhalb_der_frist():
    assert remaining_time() is None
    async with request_deadline(5):
        left = remaining_time()
        assert left is not None and 4.5 < left <= 5
    assert remaining_time() is None


def test_einstellungen_aus_umgebung(monkeypatch):
    monkeypatch.setenv("AGENT_REQUEST_TIMEOUT_S", "45")
    monkeypatch.setenv("AGENT_TOOL_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("AGENT_TOOL_TIMEOUT_S", "kein-wert")  # ungültig
    settings = ResilienceSettings.from_env()
    assert settings.request_timeout_s == 45
    assert settings.max_attempts == 3
    assert settings.tool_timeout_s == 15.0  # Standard statt ungültigem Wert


def test_englische_meldung():
    error = AgentError(ErrorCode.UPSTREAM_UNAVAILABLE)
    assert error.to_event("en")["message"].startswith("A required service")
    # Unbekannte Sprache fällt auf Deutsch zurück.
    assert "Dienst" in error.user_message("fr")


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("code", list(ErrorCode))
def test_error_ereignis_passt_zum_schema(interface_validator, code, lang):
    # Schnittstelle aus Issue #2: {"event": "error", "data": {...}}
    event = {"event": "error", "data": AgentError(code).to_event(lang)}
    interface_validator("sse-events").validate(event)
