"""Retry- und Timeout-Logik für die Tool-Aufrufe des Agenten.

Umgesetzte Anforderungen aus dem Pflichtenheft:

* US-AGT-08: Fehlgeschlagene Tool-Aufrufe werden genau einmal wiederholt.
  Danach sendet der Agent ein ``error``-Ereignis mit verständlicher Meldung,
  und die Anwendung bleibt bedienbar.
* Abschnitt 5.1: Keine Anfrage dauert länger als 60 Sekunden. Danach bricht
  der Agent ab und sendet ``error`` mit dem Code ``TIMEOUT``.
* Abschnitt 5.2: Logs enthalten keine Frageinhalte. Deshalb tragen die
  Fehler hier nur technische Angaben (Tool-Name, HTTP-Status), nie die Frage.

Aufbau:

* :class:`ResilienceSettings` liest die Grenzwerte aus Umgebungsvariablen.
* :func:`request_deadline` setzt die Gesamtfrist für eine Nutzeranfrage.
* :func:`call_with_retry` führt einen einzelnen Tool-Aufruf mit Zeitlimit
  und einer Wiederholung aus und hält dabei die Gesamtfrist ein.
* :class:`AgentError` ist der einheitliche Fehler, den die SSE-Schicht in ein
  ``error``-Ereignis übersetzt (:meth:`AgentError.to_event`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """Fehlercodes im ``error``-Ereignis (Teil des SSE-Protokolls)."""

    # Gesamtfrist der Anfrage (60 s) überschritten.
    TIMEOUT = "TIMEOUT"
    # Externer Dienst (STAC API, Tiler, Geocoder, LLM) nicht erreichbar
    # oder überlastet, auch nach der Wiederholung.
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    # Der Dienst hat die Anfrage abgelehnt (HTTP 4xx), z. B. ein ungültiger
    # CQL2-Filter. Eine Wiederholung derselben Anfrage hilft hier nicht.
    INVALID_REQUEST = "INVALID_REQUEST"
    # Alle übrigen Fehler innerhalb eines Tools.
    TOOL_FAILED = "TOOL_FAILED"


# Meldungen für Nutzerinnen und Nutzer. Sie stehen hier zentral, damit die
# Web-App sie unverändert anzeigen kann und sie leicht zu übersetzen sind.
USER_MESSAGES: dict[str, dict[ErrorCode, str]] = {
    "de": {
        ErrorCode.TIMEOUT: (
            "Die Anfrage hat zu lange gedauert und wurde nach 60 Sekunden "
            "abgebrochen. Bitte versuchen Sie es erneut oder formulieren Sie "
            "die Frage enger."
        ),
        ErrorCode.UPSTREAM_UNAVAILABLE: (
            "Ein benötigter Dienst ist gerade nicht erreichbar. Bitte "
            "versuchen Sie es in einem Moment erneut."
        ),
        ErrorCode.INVALID_REQUEST: (
            "Die Suchanfrage konnte nicht verarbeitet werden. Bitte "
            "formulieren Sie die Frage anders."
        ),
        ErrorCode.TOOL_FAILED: (
            "Bei der Bearbeitung ist ein Fehler aufgetreten. Bitte versuchen "
            "Sie es erneut."
        ),
    },
    "en": {
        ErrorCode.TIMEOUT: (
            "The request took too long and was stopped after 60 seconds. "
            "Please try again or narrow down your question."
        ),
        ErrorCode.UPSTREAM_UNAVAILABLE: (
            "A required service is currently unavailable. Please try again in a moment."
        ),
        ErrorCode.INVALID_REQUEST: (
            "The search request could not be processed. Please rephrase your question."
        ),
        ErrorCode.TOOL_FAILED: "Something went wrong. Please try again.",
    },
}

# Fehlerkategorie im Feld ``type`` des ``error``-Ereignisses (Schema aus #2).
ERROR_TYPE = "agent_error"

# Diese Fehler darf die Web-App mit einem „Erneut versuchen“-Knopf anbieten
# (Abschnitt 5.3: Fehlermeldungen jeweils mit Option zum Wiederholen).
_RETRYABLE_BY_USER = {
    ErrorCode.TIMEOUT,
    ErrorCode.UPSTREAM_UNAVAILABLE,
    ErrorCode.TOOL_FAILED,
}


class AgentError(Exception):
    """Einheitlicher Fehler des Agenten, der als SSE-Ereignis ausgeliefert wird.

    ``detail`` ist nur für Logs gedacht und darf keine Frageinhalte enthalten.
    """

    def __init__(self, code: ErrorCode, detail: str = "", *, tool: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else str(code))
        self.code = code
        self.detail = detail
        self.tool = tool

    @property
    def retryable(self) -> bool:
        """Ob die Web-App eine Wiederholung anbieten soll."""
        return self.code in _RETRYABLE_BY_USER

    def user_message(self, lang: str = "de") -> str:
        """Verständliche Meldung in der Sprache der Frage (Fallback: Deutsch)."""
        return USER_MESSAGES.get(lang, USER_MESSAGES["de"])[self.code]

    def to_event(self, lang: str = "de") -> dict[str, Any]:
        """Daten (``data``) für das SSE-Ereignis ``error``.

        Das Format folgt ``ErrorEvent`` in
        ``schemas/interfaces/sse-events.schema.json`` (Issue #2). Die SSE-Schicht
        sendet es als ``event: error`` mit diesem Objekt als ``data``.
        """
        return {
            "type": ERROR_TYPE,
            "code": str(self.code),
            "message": self.user_message(lang),
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class ResilienceSettings:
    """Grenzwerte für Zeitlimits und Wiederholungen.

    Alle Werte lassen sich über Umgebungsvariablen (``.env``) ändern, damit
    wir sie auf der Referenzhardware nachjustieren können, ohne Code zu ändern.
    """

    # Gesamtfrist je Nutzeranfrage (Abschnitt 5.1: höchstens 60 s).
    request_timeout_s: float = 60.0
    # Zeitlimit für einen einzelnen Tool-Aufruf.
    tool_timeout_s: float = 15.0
    # Anzahl der Versuche: 1 Versuch + 1 Wiederholung (US-AGT-08).
    max_attempts: int = 2
    # Wartezeit vor der Wiederholung; wächst linear mit dem Versuch.
    backoff_s: float = 0.5
    # Obergrenze für einen ``Retry-After``-Header bei HTTP 429.
    max_retry_after_s: float = 5.0

    @classmethod
    def from_env(cls) -> ResilienceSettings:
        """Liest die Einstellungen aus der Umgebung, sonst gelten die Vorgaben."""
        return cls(
            request_timeout_s=_env_float("AGENT_REQUEST_TIMEOUT_S", 60.0),
            tool_timeout_s=_env_float("AGENT_TOOL_TIMEOUT_S", 15.0),
            max_attempts=int(_env_float("AGENT_TOOL_MAX_ATTEMPTS", 2)),
            backoff_s=_env_float("AGENT_TOOL_BACKOFF_S", 0.5),
            max_retry_after_s=_env_float("AGENT_MAX_RETRY_AFTER_S", 5.0),
        )


def _env_float(name: str, default: float) -> float:
    """Liest eine Zahl aus der Umgebung; ungültige Werte fallen auf den Standard."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ungültiger Wert für %s, nutze Standard %s", name, default)
        return default


# ---------------------------------------------------------------------------
# Gesamtfrist je Anfrage
# ---------------------------------------------------------------------------

# Zeitpunkt (monotone Uhr), zu dem die aktuelle Anfrage spätestens endet.
# Ein ContextVar überträgt den Wert automatisch an alle Tasks, die innerhalb
# der Anfrage gestartet werden, auch an die Tool-Aufrufe von LangGraph.
_deadline: ContextVar[float | None] = ContextVar("vitalmap_deadline", default=None)


def remaining_time() -> float | None:
    """Verbleibende Zeit der aktuellen Anfrage in Sekunden (``None`` = keine Frist)."""
    deadline = _deadline.get()
    if deadline is None:
        return None
    return deadline - time.monotonic()


@asynccontextmanager
async def request_deadline(seconds: float | None = None) -> AsyncIterator[None]:
    """Begrenzt die Bearbeitung einer Nutzeranfrage auf ``seconds`` Sekunden.

    Verwendung im SSE-Endpunkt (Beispiel)::

        async def event_stream(...):
            try:
                async with request_deadline():
                    async for event in run_agent(...):
                        yield event
            except AgentError as err:
                yield sse(err.to_event(lang))

    Läuft die Frist ab, wird der laufende Code abgebrochen und ein
    :class:`AgentError` mit Code ``TIMEOUT`` ausgelöst.
    """
    if seconds is None:
        seconds = ResilienceSettings.from_env().request_timeout_s
    token = _deadline.set(time.monotonic() + seconds)
    try:
        # asyncio.timeout bricht den Code im Block ab, sobald die Frist abläuft,
        # und wandelt den Abbruch in einen TimeoutError um.
        async with asyncio.timeout(seconds):
            yield
    except TimeoutError as exc:
        raise AgentError(
            ErrorCode.TIMEOUT, f"Gesamtfrist von {seconds:.0f} s überschritten"
        ) from exc
    finally:
        _deadline.reset(token)


# ---------------------------------------------------------------------------
# Einzelner Tool-Aufruf mit Zeitlimit und Wiederholung
# ---------------------------------------------------------------------------


def is_retryable(exc: BaseException) -> bool:
    """Entscheidet, ob eine Wiederholung sinnvoll ist.

    Wiederholt werden nur vorübergehende Fehler: Netzwerkfehler, Zeitüberschreitung,
    HTTP 429 (zu viele Anfragen) und HTTP 5xx. HTTP 4xx (z. B. ein ungültiger
    Filter) liefert beim zweiten Mal dasselbe Ergebnis und wird nicht wiederholt.
    """
    if isinstance(exc, (TimeoutError, httpx.TransportError)):
        # httpx.TimeoutException ist eine Unterklasse von TransportError.
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


def _to_agent_error(exc: BaseException, tool: str) -> AgentError:
    """Übersetzt technische Fehler in einen :class:`AgentError`."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429 or status >= 500:
            code = ErrorCode.UPSTREAM_UNAVAILABLE
        else:
            code = ErrorCode.INVALID_REQUEST
        return AgentError(code, f"HTTP {status}", tool=tool)
    if isinstance(exc, (TimeoutError, httpx.TransportError)):
        return AgentError(ErrorCode.UPSTREAM_UNAVAILABLE, type(exc).__name__, tool=tool)
    return AgentError(ErrorCode.TOOL_FAILED, type(exc).__name__, tool=tool)


def _attempt_timeout(settings: ResilienceSettings) -> tuple[float, bool]:
    """Zeitlimit für den nächsten Versuch.

    Gibt das Limit zurück und ob es durch die Gesamtfrist begrenzt ist. Ein
    Tool darf nie länger laufen, als von der Gesamtfrist noch übrig ist.
    """
    remaining = remaining_time()
    if remaining is not None and remaining < settings.tool_timeout_s:
        return remaining, True
    return settings.tool_timeout_s, False


def _retry_delay(
    exc: BaseException, attempt: int, settings: ResilienceSettings
) -> float:
    """Wartezeit vor der nächsten Wiederholung.

    Bei HTTP 429 respektieren wir ``Retry-After`` (in Sekunden), aber nur bis
    ``max_retry_after_s``; sonst wächst die Pause linear mit dem Versuch.
    """
    delay = settings.backoff_s * attempt
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        header = exc.response.headers.get("Retry-After", "")
        if header.strip().isdigit():
            delay = min(float(header), settings.max_retry_after_s)
    remaining = remaining_time()
    if remaining is not None:
        # Nicht länger warten, als die Gesamtfrist erlaubt.
        delay = min(delay, max(remaining, 0.0))
    return delay


async def call_with_retry[T](
    func: Callable[[], Awaitable[T]],
    *,
    tool: str,
    settings: ResilienceSettings | None = None,
) -> T:
    """Führt ``func`` mit Zeitlimit aus und wiederholt sie bei Bedarf einmal.

    ``func`` ist eine Funktion ohne Argumente, die bei jedem Versuch neu
    aufgerufen wird, z. B. ``lambda: client.get(url)``. Sie muss bei einem
    fehlerhaften HTTP-Status ``raise_for_status()`` aufrufen, damit der Fehler
    hier ankommt.

    Wiederholt werden nur lesende Aufrufe; alle Tools des Agenten lesen nur.

    Raises:
        AgentError: nach dem letzten Versuch, bei nicht wiederholbaren Fehlern
            oder wenn die Gesamtfrist der Anfrage abgelaufen ist.
    """
    settings = settings or ResilienceSettings.from_env()
    last_exc: BaseException | None = None

    for attempt in range(1, settings.max_attempts + 1):
        timeout, limited_by_deadline = _attempt_timeout(settings)
        if timeout <= 0:
            raise AgentError(ErrorCode.TIMEOUT, "Gesamtfrist abgelaufen", tool=tool)
        try:
            async with asyncio.timeout(timeout):
                return await func()
        except AgentError:
            # Bereits übersetzte Fehler (z. B. aus einem verschachtelten Aufruf)
            # unverändert weiterreichen.
            raise
        except Exception as exc:
            # CancelledError erbt nicht von Exception und wird daher nicht
            # abgefangen: Ein Abbruch der Gesamtanfrage geht immer durch.
            if isinstance(exc, TimeoutError) and limited_by_deadline:
                raise AgentError(
                    ErrorCode.TIMEOUT, "Gesamtfrist während Tool-Aufruf", tool=tool
                ) from exc
            last_exc = exc
            if not is_retryable(exc) or attempt == settings.max_attempts:
                break
            delay = _retry_delay(exc, attempt, settings)
            logger.info(
                "Tool %s fehlgeschlagen (%s), Wiederholung in %.1f s",
                tool,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    if last_exc is None:  # nur bei max_attempts < 1 möglich
        raise AgentError(
            ErrorCode.TOOL_FAILED, "keine Versuche konfiguriert", tool=tool
        )
    error = _to_agent_error(last_exc, tool)
    logger.warning("Tool %s endgültig fehlgeschlagen: %s", tool, error.detail)
    raise error from last_exc
