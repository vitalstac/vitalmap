# VitalMap – KI-Agent

Python-Dienst, der Fragen in natürlicher Sprache in STAC-Anfragen übersetzt
(LangGraph, uniGPT). Die Web-App spricht ihn per Server-Sent Events an; das
Format steht in `schemas/interfaces/` (Issue #2).

## Aufbau

| Pfad | Inhalt | Issue |
| --- | --- | --- |
| `vitalmap_agent/resilience.py` | Zeitlimits, genau eine Wiederholung je Tool-Aufruf, `error`-Ereignis | #3 |
| `vitalmap_agent/evaluation/` | Auswertung des Testfragenkatalogs (SSE-Client, Prüfregeln, Bericht) | #8 |
| `eval/testfragen.yaml` | 15 Testfragen, davon 5 Fallenfragen | #8 |
| `eval/run_testfragen.py` | stellt die Testfragen an den laufenden Agenten | #8 |
| `eval/results/` | Berichte der Läufe (Markdown und JSON) | #8 |
| `tests/` | Unit-Tests (pytest), ohne Netzwerk und ohne Sprachmodell | – |

FastAPI-Endpunkt, LangGraph-Graph und STAC-Tools kommen mit den nächsten Pull
Requests dazu.

## Einrichten

Python 3.12. Alle Befehle im Ordner `ai-agents/`:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

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
