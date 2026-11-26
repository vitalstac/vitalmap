"""Tests für die LLM-Konfiguration und die Prüfregeln des Verbindungstests.

Es gibt keine Netzwerkzugriffe; geprüft wird nur die Konfiguration.
"""

import json
from types import SimpleNamespace

import pytest

from vitalmap_agent.evaluation.llm_check import evaluate_tool_calls
from vitalmap_agent.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMConfigError,
    LLMSettings,
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "AGENT_REQUEST_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_ohne_umgebung_gilt_unigpt(clean_env):
    settings = LLMSettings.from_env()
    assert (settings.base_url, settings.model) == (DEFAULT_BASE_URL, DEFAULT_MODEL)


def test_werte_aus_der_umgebung(clean_env):
    clean_env.setenv("LLM_BASE_URL", "https://gpt.uni-muenster.de/v1/")
    clean_env.setenv("LLM_MODEL", "Qwen3.8-27B")
    clean_env.setenv("LLM_API_KEY", " sk-test ")
    settings = LLMSettings.from_env()
    assert settings.base_url == "https://gpt.uni-muenster.de/v1"
    assert settings.model == "Qwen3.8-27B"
    assert settings.api_key == "sk-test"


def test_schluessel_steht_nie_im_repr():
    assert "sk-geheim" not in repr(LLMSettings(api_key="sk-geheim"))


@pytest.mark.parametrize(
    "key", ["", "your-api-key-here", "HIER-DEN-SCHLUESSEL-EINFUEGEN"]
)
def test_platzhalter_gilt_als_fehlender_schluessel(key):
    with pytest.raises(LLMConfigError, match="gpt-api.uni-muenster.de"):
        LLMSettings(api_key=key).require_key()


def test_lokales_modell_braucht_keinen_schluessel():
    settings = LLMSettings(base_url="http://ollama:11434/v1", model="qwen3:4b")
    assert settings.is_local
    settings.require_key()  # kein Fehler


def test_origin_fuer_key_info():
    assert LLMSettings().origin == "https://gpt.uni-muenster.de"


def test_openai_client_nutzt_endpunkt_ohne_eigene_wiederholungen():
    pytest.importorskip("openai")
    client = LLMSettings(api_key="sk-test").openai_client()
    assert str(client.base_url).rstrip("/") == DEFAULT_BASE_URL
    assert client.max_retries == 0


def test_chat_model_fuer_langgraph():
    pytest.importorskip("langchain_openai")
    model = LLMSettings(api_key="sk-test", model="Qwen3.8-27B").chat_model()
    assert model.model_name == "Qwen3.8-27B"


# -- Prüfregeln des Tool-Calling-Tests --------------------------------------------


def call(name="search_collections", **args):
    return SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def test_korrekter_aufruf_besteht():
    ok = call(
        q="PM2.5", bbox=[5.87, 50.32, 9.46, 52.53], datetime="2020-01-01/2023-12-31"
    )
    assert evaluate_tool_calls([ok]) == []


def test_ohne_aufruf_nicht_bestanden():
    assert evaluate_tool_calls(None) == ["kein Tool-Aufruf"]


def test_falsche_bbox_und_fehlender_zeitraum():
    bad = call(q="PM2.5", bbox=[139.5, 35.5, 140.0, 35.9])  # Tokio
    problems = evaluate_tool_calls([bad])
    assert any("BBox" in p for p in problems) and any("Zeitraum" in p for p in problems)


def test_kaputtes_json():
    broken = SimpleNamespace(
        function=SimpleNamespace(name="search_collections", arguments="{")
    )
    assert "kein gültiges JSON" in evaluate_tool_calls([broken])[-1]
