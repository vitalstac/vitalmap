"""FastAPI-Dienst des Agenten: ``POST /api/agent/chat`` mit Server-Sent Events.

Anfrage und Ereignisse folgen ``schemas/interfaces/`` (Issue #2). Jede Anfrage
hat eine Gesamtfrist (Standard 60 s, Abschnitt 5.1); Fehler kommen als
``error``-Ereignis mit verständlicher Meldung, die Anwendung bleibt bedienbar
(US-AGT-08). Logs enthalten keine Frageinhalte (Abschnitt 5.2).

Starten (im Ordner ``ai-agents/``)::

    uvicorn vitalmap_agent.api:app --port 8000
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from vitalmap_agent.agent import WORLD_BBOX, OpenAIBackend, VitalMapAgent
from vitalmap_agent.llm import LLMSettings, load_env_file
from vitalmap_agent.resilience import AgentError, ErrorCode, request_deadline
from vitalmap_agent.stac import StacClient

logger = logging.getLogger(__name__)


class MapContext(BaseModel):
    """Anwendungskontext der Web-App (chat-request.schema.json)."""

    bbox: list[float] = Field(
        default_factory=lambda: list(WORLD_BBOX), min_length=4, max_length=4
    )
    zoom: float = Field(0, ge=0, le=24)
    layers: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    datetime: str | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    lang: Literal["de", "en"] = "de"
    context: MapContext = Field(default_factory=MapContext)


def sse(event: dict[str, Any]) -> str:
    """Ein Ereignis im SSE-Format: Typ in ``event:``, Daten als JSON."""
    data = json.dumps(event["data"], ensure_ascii=False)
    return f"event: {event['event']}\ndata: {data}\n\n"


def create_app(agent: VitalMapAgent | None = None) -> FastAPI:
    """Baut die App; Tests übergeben einen Agenten mit Attrappen."""
    state: dict[str, Any] = {"agent": agent}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if state["agent"] is None:
            load_env_file()
            settings = LLMSettings.from_env()
            state["agent"] = VitalMapAgent(OpenAIBackend(settings), StacClient())
            logger.info(
                "Agent bereit: Modell %s, STAC API %s",
                settings.model,
                state["agent"].stac.base_url,
            )
        yield
        await state["agent"].stac.aclose()

    app = FastAPI(title="VitalMap-Agent", version="0.1.0", lifespan=lifespan)
    origins = os.getenv("AGENT_CORS_ORIGINS", "http://localhost:5173")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    @app.get("/api/agent/health")
    async def health() -> dict[str, Any]:
        current = state["agent"]
        backend = getattr(current.backend, "settings", None)
        return {
            "status": "ok",
            "model": getattr(backend, "model", None),
            "stac_api": current.stac.base_url,
        }

    @app.post("/api/agent/chat")
    async def chat(request: ChatRequest) -> StreamingResponse:
        current = state["agent"]

        async def events() -> AsyncIterator[str]:
            try:
                async with request_deadline():
                    async for event in current.run(
                        request.session_id,
                        request.message,
                        request.lang,
                        request.context.model_dump(),
                    ):
                        yield sse(event)
            except AgentError as err:
                logger.warning("Anfrage abgebrochen: %s (%s)", err.code, err.tool)
                yield sse({"event": "error", "data": err.to_event(request.lang)})
            except Exception:
                logger.exception("Unerwarteter Fehler im Agenten")
                err = AgentError(ErrorCode.TOOL_FAILED)
                yield sse({"event": "error", "data": err.to_event(request.lang)})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
