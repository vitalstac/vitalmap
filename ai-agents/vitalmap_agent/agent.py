"""Der VitalMap-Agent als LangGraph-Graph (US-AGT-01, US-AGT-04, US-AGT-05).

Ablauf einer Frage::

    START -> model --(Tool-Aufruf)--> tools --> model --> ... --> END

* ``model`` ruft das Sprachmodell (uniGPT, OpenAI-kompatibel) mit den Tools
  ``search_collections`` und ``get_collection`` auf und streamt den Text.
* ``tools`` führt die Tool-Aufrufe gegen die STAC API aus.
* Der Verlauf je Session bleibt im Checkpointer (thread_id = Session-ID), so
  beziehen sich Folgefragen auf die vorige Suche.

Die Ereignisse für die Web-App (``status``, ``stac_query``, ``token``, ``done``)
entstehen in den Knoten und werden über den Stream-Writer von LangGraph
weitergereicht. Format: ``schemas/interfaces/sse-events.schema.json``.

Grounding (Stufe 1): Das Modell darf Datensätze nur als ``[[collection-id]]``
nennen. Nach der Antwort prüfen wir jede Markierung gegen die Tool-Ergebnisse
desselben Gesprächs und entfernen alles, was nicht aus dem Katalog stammt. Die
vollständige Grounding-Prüfung (Titel, URLs) folgt in #4.
"""

from __future__ import annotations

import json
import logging
import operator
import re
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from vitalmap_agent.llm import LLMSettings
from vitalmap_agent.resilience import AgentError, ErrorCode
from vitalmap_agent.stac import StacClient

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
WORLD_BBOX = [-180.0, -90.0, 180.0, 90.0]

SYSTEM_PROMPT = """\
Du bist der Suchassistent von VitalMap, einem Katalog für Gesundheitsdaten \
(STAC). Du hilfst medizinischen Fachleuten ohne GIS-Kenntnisse, passende \
Datensätze zu finden.

Regeln:
1. Suche Datensätze immer mit dem Tool search_collections. Für Details zu \
einem Datensatz nutze get_collection.
2. Nenne nur Datensätze, die in einem Tool-Ergebnis dieses Gesprächs \
vorkommen. Erfinde niemals Datensätze, Titel, Links, Zahlen oder Zeiträume.
3. Nenne jeden Datensatz mit seiner ID in doppelten eckigen Klammern, z. B. \
[[eea-pm25-annual-mean]], gefolgt von einer kurzen Beschreibung.
4. Findest du nichts Passendes, antworte mit „Dazu gibt es keine passenden \
Datensätze im Katalog.“ und schlage höchstens Datensätze vor, die du \
tatsächlich gefunden hast. Rate nicht.
5. Nennt die Frage einen Ort, setze bbox selbst als [West, Süd, Ost, Nord] \
in WGS84 (eine grobe Umrandung reicht) und sage, welches Gebiet du gesucht hast.
6. Nennt die Frage einen Zeitraum, setze datetime als Intervall, z. B. \
2020-01-01/2023-12-31.
7. Der Suchbegriff q ist ein kurzes Stichwort (z. B. PM2.5, Hausärzte, \
Hitze). Bleibt die Suche leer, versuche einmal ein anderes Stichwort oder \
lass bbox und datetime weg.
8. Antworte knapp, sachlich und in der Sprache der Frage."""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_collections",
            "description": (
                "Durchsucht den VitalMap-Katalog nach Datensätzen (STAC Collection "
                "Search). Liefert ID, Titel, Beschreibung, Ausdehnung und "
                "Health-Felder der Treffer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Stichwort, z. B. PM2.5"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "[West, Süd, Ost, Nord] in WGS84",
                    },
                    "datetime": {
                        "type": "string",
                        "description": "Zeitraum, z. B. 2020-01-01/2023-12-31",
                    },
                    "filter": {
                        "type": "object",
                        "description": (
                            "Optionaler CQL2-JSON-Filter auf Health-Felder, z. B. "
                            '{"op":"=","args":[{"property":"health:status"},'
                            '"onGoing"]}'
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_collection",
            "description": "Alle Metadaten eines Datensatzes anhand seiner ID.",
            "parameters": {
                "type": "object",
                "properties": {"collection_id": {"type": "string"}},
                "required": ["collection_id"],
            },
        },
    },
]

MARKER_RE = re.compile(r"\[\[\s*([^\[\]\s]+?)\s*\]\]")
STATUS = {
    "de": {
        "start": "Frage wird verstanden …",
        "search_collections": "Durchsuche den Katalog …",
        "get_collection": "Lese die Metadaten …",
        "answer": "Werte die Treffer aus …",
    },
    "en": {
        "start": "Understanding the question …",
        "search_collections": "Searching the catalogue …",
        "get_collection": "Reading the metadata …",
        "answer": "Reviewing the results …",
    },
}
REMOVED_NOTE = {"de": "[nicht im Katalog]", "en": "[not in the catalogue]"}


# ---------------------------------------------------------------------------
# Sprachmodell
# ---------------------------------------------------------------------------


class ChatBackend(Protocol):
    """Schnittstelle zum Sprachmodell; in Tests durch ein Skript ersetzbar."""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_token: Callable[[str], None],
    ) -> dict[str, Any]: ...


class OpenAIBackend:
    """Chat Completions mit Streaming gegen uniGPT oder Ollama."""

    def __init__(self, settings: LLMSettings) -> None:
        from openai import AsyncOpenAI

        settings.require_key()
        self.settings = settings
        self.client = AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key if settings.has_key else "ollama",
            timeout=settings.timeout_s,
            max_retries=0,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_token: Callable[[str], None],
    ) -> dict[str, Any]:
        for attempt in (1, 2):
            emitted = False
            try:
                content: list[str] = []
                calls: dict[int, dict[str, Any]] = {}
                stream = await self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    tools=tools,
                    temperature=0.2,
                    stream=True,
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        emitted = True
                        content.append(delta.content)
                        on_token(delta.content)
                    for tc in delta.tool_calls or []:
                        call = calls.setdefault(
                            tc.index,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if tc.id:
                            call["id"] = tc.id
                        if tc.function and tc.function.name:
                            call["function"]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            call["function"]["arguments"] += tc.function.arguments
                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": "".join(content) or None,
                }
                if calls:
                    message["tool_calls"] = [calls[i] for i in sorted(calls)]
                return message
            except Exception as exc:
                error = _llm_error(exc)
                # Eine Wiederholung, aber nur solange noch kein Text gestreamt wurde.
                if (
                    attempt == 1
                    and not emitted
                    and error.code is not (ErrorCode.INVALID_REQUEST)
                ):
                    logger.info("LLM-Aufruf fehlgeschlagen (%s), Wiederholung", error)
                    continue
                raise error from exc
        raise AgentError(ErrorCode.TOOL_FAILED, "unerreichbar", tool="llm")


def _llm_error(exc: Exception) -> AgentError:
    """Übersetzt Fehler des OpenAI-Clients in einen AgentError."""
    if isinstance(exc, AgentError):
        return exc
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and 400 <= status < 500 and status != 429:
        return AgentError(ErrorCode.INVALID_REQUEST, f"LLM HTTP {status}", tool="llm")
    return AgentError(ErrorCode.UPSTREAM_UNAVAILABLE, type(exc).__name__, tool="llm")


# ---------------------------------------------------------------------------
# Grounding, Stufe 1
# ---------------------------------------------------------------------------


def ground_answer(
    answer: str, known_ids: set[str], lang: str = "de"
) -> tuple[str, dict[str, Any]]:
    """Entfernt markierte Datensätze, die in keinem Tool-Ergebnis vorkamen."""
    removed: list[str] = []
    cited: list[str] = []

    def replace(match: re.Match[str]) -> str:
        cid = match.group(1)
        if cid in known_ids:
            if cid not in cited:
                cited.append(cid)
            return f"[[{cid}]]"
        removed.append(cid)
        return REMOVED_NOTE.get(lang, REMOVED_NOTE["de"])

    checked = MARKER_RE.sub(replace, answer)
    # Bekannte IDs, die ohne Markierung genannt wurden, zählen auch als Beleg.
    for cid in sorted(known_ids):
        if cid not in cited and cid in checked:
            cited.append(cid)
    report = {"grounded": not removed, "removed": removed, "citations": cited}
    return checked, report


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def _merge(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    return {**left, **right}


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]
    known: Annotated[dict[str, str], _merge]  # Collection-ID -> Titel
    rounds: int
    lang: str
    context: dict[str, Any]


def _context_note(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    lines = []
    bbox = context.get("bbox")
    if bbox and list(bbox) != WORLD_BBOX:
        lines.append(f"Aktueller Kartenausschnitt (bbox): {bbox}")
    if context.get("datetime"):
        lines.append(f"Aktiver Zeitraum: {context['datetime']}")
    for key, label in (
        ("datasets", "Angezeigte Datensätze"),
        ("selected", "Ausgewählt"),
    ):
        if context.get(key):
            lines.append(f"{label}: {', '.join(context[key])}")
    if not lines:
        return ""
    return (
        "\n\nAnwendungskontext (nutze den Kartenausschnitt als bbox, wenn die "
        "Frage keinen Ort nennt, und sage das):\n" + "\n".join(lines)
    )


class VitalMapAgent:
    """Baut den Graphen und liefert die SSE-Ereignisse einer Anfrage."""

    def __init__(self, backend: ChatBackend, stac: StacClient) -> None:
        self.backend = backend
        self.stac = stac
        self.graph = self._build()

    def _build(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("model", self._model_node)
        graph.add_node("tools", self._tools_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", self._route, {"tools": "tools", END: END})
        graph.add_edge("tools", "model")
        return graph.compile(checkpointer=MemorySaver())

    @staticmethod
    def _route(state: AgentState) -> str:
        last = state["messages"][-1]
        if last.get("tool_calls") and state.get("rounds", 0) < MAX_TOOL_ROUNDS:
            return "tools"
        return END

    async def _model_node(self, state: AgentState) -> dict[str, Any]:
        writer = get_stream_writer()
        lang = state.get("lang", "de")
        system = SYSTEM_PROMPT + _context_note(state.get("context"))
        messages = [{"role": "system", "content": system}, *state["messages"]]
        tools = TOOLS if state.get("rounds", 0) < MAX_TOOL_ROUNDS else []
        if state.get("rounds", 0) > 0:
            writer({"event": "status", "data": {"message": STATUS[lang]["answer"]}})
        message = await self.backend.complete(
            messages,
            tools,
            lambda text: writer({"event": "token", "data": {"text": text}}),
        )
        return {"messages": [message], "rounds": state.get("rounds", 0) + 1}

    async def _tools_node(self, state: AgentState) -> dict[str, Any]:
        writer = get_stream_writer()
        lang = state.get("lang", "de")
        results: list[dict[str, Any]] = []
        known: dict[str, str] = {}
        for call in state["messages"][-1].get("tool_calls", []):
            name = call["function"]["name"]
            writer(
                {
                    "event": "status",
                    "data": {"message": STATUS[lang].get(name, name)},
                }
            )
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
                if name == "search_collections":
                    data, event = await self.stac.search_collections(
                        q=args.get("q"),
                        bbox=args.get("bbox"),
                        datetime=args.get("datetime"),
                        filter=args.get("filter"),
                    )
                    payload: Any = {"collections": data, "count": len(data)}
                    hits = data
                elif name == "get_collection":
                    data, event = await self.stac.get_collection(args["collection_id"])
                    payload, hits = data, [data]
                else:
                    raise AgentError(
                        ErrorCode.INVALID_REQUEST, f"unbekanntes Tool {name}"
                    )
                writer({"event": "stac_query", "data": event})
                known.update(
                    {h["id"]: h.get("title") or "" for h in hits if h.get("id")}
                )
            except AgentError as err:
                if err.code is not ErrorCode.INVALID_REQUEST:
                    raise
                # Ungültige Anfrage (z. B. Filter): das Modell soll es anders versuchen.
                payload = {"error": "Die Anfrage war ungültig.", "detail": err.detail}
            except (ValueError, KeyError, TypeError):
                payload = {"error": "Ungültige Tool-Argumente."}
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )
        return {"messages": results, "known": known}

    async def run(
        self,
        session_id: str,
        message: str,
        lang: str = "de",
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Bearbeitet eine Nutzerfrage und liefert die SSE-Ereignisse."""
        lang = lang if lang in STATUS else "de"
        yield {"event": "status", "data": {"message": STATUS[lang]["start"]}}
        config = {"configurable": {"thread_id": session_id}}
        inputs = {
            "messages": [{"role": "user", "content": message}],
            "rounds": 0,
            "lang": lang,
            "context": context or {},
        }
        async for event in self.graph.astream(inputs, config, stream_mode="custom"):
            yield event
        state = (await self.graph.aget_state(config)).values
        answer = state["messages"][-1].get("content") or ""
        # Jede Antwort wird neu geprüft, auch Folgeantworten im selben Gespräch.
        checked, report = ground_answer(answer, set(state.get("known", {})), lang)
        yield {"event": "done", "data": {"answer": checked, "grounding": report}}
