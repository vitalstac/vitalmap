# VitalMap – KI-Agent

Python-Dienst, der Fragen in natürlicher Sprache in STAC-Anfragen übersetzt
(LangGraph, uniGPT). Die Web-App spricht ihn per Server-Sent Events an; das
Format steht in `schemas/interfaces/` (Issue #2).

## Aufbau

| Pfad | Inhalt | Issue |
| --- | --- | --- |
| `vitalmap_agent/api.py` | FastAPI-Dienst, `POST /api/agent/chat` mit SSE, `GET /api/agent/health` | US-AGT-01 |
| `vitalmap_agent/agent.py` | LangGraph-Graph (Modell ↔ Tools), Verlauf je Session, Grounding Stufe 1 | US-AGT-01, -04, -05 |
| `vitalmap_agent/stac.py` | Tools `search_collections` und `get_collection` gegen die STAC API | US-AGT-01 |
| `vitalmap_agent/cli.py` | Terminal-Client, zeigt die Ereignisse live | – |
| `demo/` | Demo-Katalog mit 6 Beispieldatensätzen und Startskript für die Vorführung | – |
| `vitalmap_agent/llm.py` | Anbindung des Sprachmodells (uniGPT oder Ollama) über `.env` | US-AGT-10 |
| `eval/check_llm.py` | Verbindungs- und Tool-Calling-Test mit uniGPT | R3 |
| `vitalmap_agent/resilience.py` | Zeitlimits, genau eine Wiederholung je Tool-Aufruf, `error`-Ereignis | #3 |
| `vitalmap_agent/evaluation/` | Auswertung des Testfragenkatalogs (SSE-Client, Prüfregeln, Bericht) | #8 |
| `eval/testfragen.yaml` | 15 Testfragen, davon 5 Fallenfragen | #8 |
| `eval/run_testfragen.py` | stellt die Testfragen an den laufenden Agenten | #8 |
| `eval/results/` | Berichte der Läufe (Markdown und JSON) | #8 |
| `tests/` | Unit-Tests (pytest), ohne Netzwerk und ohne Sprachmodell | – |

## Starten

```bash
uvicorn vitalmap_agent.api:app --port 8000          # braucht STAC_API_URL und LLM_* aus der .env
python -m vitalmap_agent.cli "Welche Datensätze zeigen PM2.5 in NRW?"
python demo/run_demo.py                             # alles zusammen mit Demo-Katalog
```

Die Vorführung ist in `demo/README.md` beschrieben.

## Einrichten

Python 3.12. Alle Befehle im Ordner `ai-agents/`:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

Für den LangGraph-Agenten zusätzlich `pip install -e ".[agent,dev]"`. Unter
Windows auf ARM fehlt dafür ein Wheel von `tiktoken`; dort laufen die übrigen
Teile trotzdem.

## uniGPT anbinden

1. Unter https://gpt-api.uni-muenster.de mit der Uni-Kennung anmelden und
   „Generate Credential“ klicken.
2. `.env.example` im Wurzelverzeichnis als `.env` kopieren und den Schlüssel bei
   `LLM_API_KEY` eintragen. Die `.env` steht im `.gitignore`.
3. Verbindung und Tool-Calling prüfen:

```bash
python eval/check_llm.py                                     # DeepSeek-V4-Flash
python eval/check_llm.py --models DeepSeek-V4-Flash,Qwen3.8-27B
```

Mit dem Self-Service-Schlüssel sind nur `DeepSeek-V4-Flash` und `Qwen3.8-27B`
freigeschaltet; höchstens 4 parallele Anfragen je Schlüssel. Budget und Grenzen
zeigt `https://gpt.uni-muenster.de/key/info`.

## Tests und Linting

```bash
python -m pytest
ruff check .
ruff format --check .
```

Die Schema-Tests prüfen die Ereignisse gegen `schemas/interfaces/`. Fehlt der
Ordner, werden sie übersprungen.

## Umgebungsvariablen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `AGENT_REQUEST_TIMEOUT_S` | `60` | Gesamtfrist je Nutzeranfrage (Pflichtenheft 5.1) |
| `AGENT_TOOL_TIMEOUT_S` | `15` | Zeitlimit je Tool-Versuch |
| `AGENT_TOOL_MAX_ATTEMPTS` | `2` | 1 Versuch + 1 Wiederholung (US-AGT-08) |
| `AGENT_TOOL_BACKOFF_S` | `0.5` | Pause vor der Wiederholung |
| `AGENT_MAX_RETRY_AFTER_S` | `5` | Obergrenze für `Retry-After` bei HTTP 429 |
| `AGENT_CHAT_URL` | `http://localhost:8000/api/agent/chat` | SSE-Endpunkt für den Testfragenkatalog |
