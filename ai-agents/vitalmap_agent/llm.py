"""Anbindung des Sprachmodells: uniGPT oder ein lokales Modell über Ollama.

US-AGT-10: ``LLM_BASE_URL``, ``LLM_MODEL`` und ``LLM_API_KEY`` kommen aus der
Umgebung bzw. aus der ``.env``. Beide Anbieter sprechen die OpenAI-kompatible
Chat-Completions-API, deshalb reicht ein Wechsel der drei Werte:

* uniGPT: ``https://gpt.uni-muenster.de/v1`` mit ``DeepSeek-V4-Flash`` oder
  ``Qwen3.8-27B``; Schlüssel aus https://gpt-api.uni-muenster.de
* lokal: ``http://ollama:11434/v1`` mit ``qwen3:4b``; ohne Schlüssel

Wiederholungen übernimmt :mod:`vitalmap_agent.resilience`, deshalb sind die
eingebauten Wiederholungen der Clients hier abgeschaltet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://gpt.uni-muenster.de/v1"
DEFAULT_MODEL = "DeepSeek-V4-Flash"

# Werte, die nur als Platzhalter in .env.example stehen.
PLACEHOLDER_KEYS = {"", "your-api-key-here", "HIER-DEN-SCHLUESSEL-EINFUEGEN"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "ollama", "host.docker.internal"}


class LLMConfigError(RuntimeError):
    """Die Konfiguration des Sprachmodells ist unvollständig."""


def load_env_file(path: str | Path | None = None) -> Path | None:
    """Lädt die ``.env`` (Standard: nächste ``.env`` ab dem aktuellen Ordner aufwärts).

    Bereits gesetzte Umgebungsvariablen haben Vorrang, damit Docker Compose
    und CI die Werte überschreiben können.
    """
    from dotenv import find_dotenv, load_dotenv

    found = str(path) if path else find_dotenv(usecwd=True)
    if not found:
        return None
    load_dotenv(found, override=False)
    return Path(found)


@dataclass(frozen=True)
class LLMSettings:
    """Verbindungsdaten für das Sprachmodell.

    Der Schlüssel erscheint nie in ``repr`` und damit auch nicht in Logs.
    """

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = field(default="", repr=False)
    timeout_s: float = 60.0

    @classmethod
    def from_env(cls) -> LLMSettings:
        """Liest die Werte aus der Umgebung; fehlende Werte fallen auf uniGPT zurück."""
        return cls(
            base_url=(os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL)
            .strip()
            .rstrip("/"),
            model=(os.getenv("LLM_MODEL") or DEFAULT_MODEL).strip(),
            api_key=(os.getenv("LLM_API_KEY") or "").strip(),
            timeout_s=float(os.getenv("AGENT_REQUEST_TIMEOUT_S") or 60),
        )

    @property
    def is_local(self) -> bool:
        """Lokales Modell (Ollama), das keinen Schlüssel braucht."""
        return (urlsplit(self.base_url).hostname or "") in LOCAL_HOSTS

    @property
    def has_key(self) -> bool:
        return self.api_key not in PLACEHOLDER_KEYS

    @property
    def origin(self) -> str:
        """Basis-URL ohne Pfad, z. B. für ``/key/info`` bei uniGPT."""
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    def require_key(self) -> None:
        """Bricht mit einer verständlichen Meldung ab, wenn der Schlüssel fehlt."""
        if not self.is_local and not self.has_key:
            raise LLMConfigError(
                "LLM_API_KEY fehlt in der .env. Einen uniGPT-Schlüssel erzeugt man "
                "unter https://gpt-api.uni-muenster.de (Generate Credential)."
            )

    def with_model(self, model: str) -> LLMSettings:
        return LLMSettings(self.base_url, model, self.api_key, self.timeout_s)

    def openai_client(self) -> Any:
        """OpenAI-kompatibler Client für direkte Aufrufe (z. B. Verbindungstest)."""
        from openai import OpenAI

        self.require_key()
        return OpenAI(
            base_url=self.base_url,
            api_key=self.api_key if self.has_key else "ollama",
            timeout=self.timeout_s,
            max_retries=0,
        )

    def chat_model(self, **kwargs: Any) -> Any:
        """Chatmodell für den LangGraph-Agenten (braucht ``langchain-openai``)."""
        from langchain_openai import ChatOpenAI

        self.require_key()
        return ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key if self.has_key else "ollama",
            model=self.model,
            timeout=self.timeout_s,
            max_retries=0,
            **kwargs,
        )
