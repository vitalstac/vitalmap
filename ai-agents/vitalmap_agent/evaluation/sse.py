"""Kleiner SSE-Client, um den Agenten wie die Web-App abzufragen.

Unterstützt beide üblichen Varianten des Ereignistyps:

* ``event: token`` plus ``data: {...}`` (Typ in der Zeile ``event:``)
* nur ``data: {"type": "token", ...}`` (Typ im JSON)

Die Anfrage an den Agenten baut :func:`build_payload` nach
``schemas/interfaces/chat-request.schema.json`` (Issue #2); der Endpunkt ist
``POST /api/agent/chat``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class SseEvent:
    type: str
    data: dict[str, Any]
    t: float  # Sekunden seit dem Absenden der Anfrage


@dataclass
class AgentRun:
    """Alle Ereignisse einer Anfrage, mit bequemen Auswertungen."""

    question: str
    events: list[SseEvent] = field(default_factory=list)
    transport_error: str | None = None

    def of_type(self, kind: str) -> list[SseEvent]:
        return [e for e in self.events if e.type == kind]

    @property
    def t_first_event(self) -> float | None:
        return self.events[0].t if self.events else None

    @property
    def t_done(self) -> float | None:
        done = self.of_type("done")
        return done[0].t if done else None

    @property
    def error_code(self) -> str | None:
        errors = self.of_type("error")
        return str(errors[0].data.get("code")) if errors else self.transport_error

    @property
    def answer(self) -> str:
        """Finale Antwort: bevorzugt der geprüfte Text aus ``done``, sonst die Tokens.

        Hintergrund: Die Grounding-Prüfung läuft nach dem Streaming. Der
        geprüfte Text sollte deshalb im ``done``-Ereignis stehen.
        """
        for event in self.of_type("done"):
            for key in ("answer", "text", "content"):
                if isinstance(event.data.get(key), str):
                    return event.data[key]
        parts = []
        for event in self.of_type("token"):
            for key in ("text", "content", "delta", "token"):
                if isinstance(event.data.get(key), str):
                    parts.append(event.data[key])
                    break
        return "".join(parts)


def parse_sse_lines(lines: Iterable[str]) -> Iterable[tuple[str, dict[str, Any]]]:
    """Zerlegt SSE-Zeilen in (Typ, Daten). Ein Ereignis endet mit einer Leerzeile."""
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> tuple[str, dict[str, Any]] | None:
        if not data_lines:
            return None
        raw = "\n".join(data_lines)
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"text": raw}  # z. B. reiner Text als Token
        if not isinstance(data, dict):
            data = {"value": data}
        kind = event_name or str(data.get("type", "message"))
        return kind, data

    for line in lines:
        line = line.rstrip("\r")
        if line == "":
            item = flush()
            if item:
                yield item
            event_name, data_lines = None, []
        elif line.startswith(":"):
            continue  # Kommentar / Keep-alive
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    item = flush()
    if item:
        yield item


# Neutraler Anwendungskontext für Testfragen: ganze Welt, keine Layer, keine
# Auswahl, keine Filter. So hängt das Ergebnis nur von der Frage ab.
NEUTRAL_CONTEXT: dict[str, Any] = {
    "bbox": [-180.0, -90.0, 180.0, 90.0],
    "zoom": 0,
    "layers": [],
    "datasets": [],
    "selected": [],
    "filters": {},
    "datetime": None,
}


def build_payload(
    question: str, session_id: str | None = None, lang: str = "de"
) -> dict[str, Any]:
    """Anfrage an den Agenten nach ``chat-request.schema.json`` (Issue #2).

    Jede Testfrage bekommt eine neue Session, damit sich die Fragen nicht
    gegenseitig beeinflussen.
    """
    return {
        "session_id": session_id or f"eval-{uuid.uuid4()}",
        "message": question,
        "lang": lang,
        "context": {**NEUTRAL_CONTEXT, "bbox": list(NEUTRAL_CONTEXT["bbox"])},
    }


async def stream_agent(
    url: str,
    question: str,
    *,
    timeout_s: float = 65.0,
    client: httpx.AsyncClient | None = None,
) -> AgentRun:
    """Schickt eine Frage und sammelt alle Ereignisse bis ``done`` oder ``error``."""
    run = AgentRun(question=question)
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=10.0))
    start = time.perf_counter()
    try:
        async with client.stream(
            "POST",
            url,
            json=build_payload(question),
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            async for kind, data in _aparse(response.aiter_lines()):
                run.events.append(SseEvent(kind, data, time.perf_counter() - start))
                if kind in ("done", "error"):
                    break
    except httpx.HTTPError as exc:
        run.transport_error = type(exc).__name__
    finally:
        if own_client:
            await client.aclose()
    return run


async def _aparse(
    lines: AsyncIterator[str],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Asynchrone Variante von :func:`parse_sse_lines`."""
    buffer: list[str] = []
    async for line in lines:
        buffer.append(line)
        if line.rstrip("\r") == "":
            for item in parse_sse_lines(buffer):
                yield item
            buffer = []
    for item in parse_sse_lines(buffer):
        yield item
