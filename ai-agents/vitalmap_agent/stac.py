"""Zugriff auf die STAC API: die Tools ``search_collections`` und ``get_collection``.

Jeder Aufruf läuft über :func:`~vitalmap_agent.resilience.call_with_retry`
(Zeitlimit, eine Wiederholung) und liefert neben dem Ergebnis die Daten für das
SSE-Ereignis ``stac_query``, damit die Web-App die ausgeführte Anfrage anzeigen
kann (US-WEB-07, Transparenz).

Dem Sprachmodell geben wir nur eine kompakte Zusammenfassung jeder Collection,
damit es nichts erfinden muss und der Kontext klein bleibt.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from vitalmap_agent.resilience import AgentError, ErrorCode, call_with_retry

DEFAULT_STAC_API_URL = "http://localhost:8080"

HEALTH_FIELDS = (
    "health:status",
    "health:update_frequency",
    "health:representation_type",
    "health:spatial_resolution",
    "health:temporal_resolution",
    "health:scale",
    "health:format",
)


def summarize(collection: dict[str, Any]) -> dict[str, Any]:
    """Kompakte Sicht auf eine Collection für das Sprachmodell."""
    extent = collection.get("extent", {})
    bbox = (extent.get("spatial", {}).get("bbox") or [None])[0]
    interval = (extent.get("temporal", {}).get("interval") or [[None, None]])[0]
    summary: dict[str, Any] = {
        "id": collection.get("id"),
        "title": collection.get("title"),
        "description": (collection.get("description") or "")[:300],
        "license": collection.get("license"),
        "providers": [p.get("name") for p in collection.get("providers", [])],
        "bbox": bbox,
        "temporal_interval": interval,
        "keywords": collection.get("keywords", [])[:12],
    }
    summary.update({k: collection[k] for k in HEALTH_FIELDS if k in collection})
    return summary


class StacClient:
    """Lesender Client für die STAC API (stac-fastapi-pgstac)."""

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        url = base_url or os.getenv("STAC_API_URL") or DEFAULT_STAC_API_URL
        self.base_url = url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get_json(self, path: str, params: dict[str, str], tool: str) -> Any:
        url = f"{self.base_url}{path}"

        async def fetch() -> Any:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        return await call_with_retry(fetch, tool=tool)

    def _url(self, path: str, params: dict[str, str]) -> str:
        return str(httpx.URL(f"{self.base_url}{path}", params=params))

    async def search_collections(
        self,
        q: str | None = None,
        bbox: list[float] | None = None,
        datetime: str | None = None,
        filter: dict[str, Any] | None = None,  # noqa: A002 – Name aus der STAC API
        limit: int = 10,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Collection Search: ``GET /collections`` mit q, bbox, datetime, filter.

        Returns:
            (Zusammenfassungen der Treffer, Daten für das ``stac_query``-Ereignis)
        """
        params: dict[str, str] = {"limit": str(max(1, min(int(limit), 50)))}
        if q:
            params["q"] = q
        if bbox:
            if len(bbox) != 4:
                raise AgentError(ErrorCode.INVALID_REQUEST, "bbox braucht 4 Zahlen")
            params["bbox"] = ",".join(f"{float(v):g}" for v in bbox)
        if datetime:
            params["datetime"] = datetime
        if filter:
            params["filter"] = json.dumps(filter, separators=(",", ":"))
            params["filter-lang"] = "cql2-json"
        data = await self._get_json("/collections", params, "search_collections")
        collections = data.get("collections", []) if isinstance(data, dict) else []
        summaries = [summarize(c) for c in collections]
        event = {
            "method": "GET",
            "url": self._url("/collections", params),
            "body": None,
            "collections": [{"id": s["id"], "title": s["title"]} for s in summaries],
        }
        return summaries, event

    async def get_collection(
        self, collection_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Metadaten einer Collection: ``GET /collections/{id}``."""
        path = f"/collections/{collection_id}"
        data = await self._get_json(path, {}, "get_collection")
        summary = summarize(data)
        summary["links"] = [
            {
                "rel": link.get("rel"),
                "href": link.get("href"),
                "title": link.get("title"),
            }
            for link in data.get("links", [])
            if link.get("rel") in {"license", "via", "describedby", "cite-as"}
        ]
        summary["assets"] = {
            key: {"type": asset.get("type"), "roles": asset.get("roles")}
            for key, asset in data.get("assets", {}).items()
        }
        event = {
            "method": "GET",
            "url": self._url(path, {}),
            "body": None,
            "collections": [{"id": summary["id"], "title": summary["title"]}],
        }
        return summary, event
