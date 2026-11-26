# Demo: KI-Agent mit uniGPT im Terminal

Zeigt in wenigen Minuten, was der Agent kann: Er versteht eine Frage, sucht
selbst im Katalog, antwortet und belegt jeden genannten Datensatz.

## Vorbereitung (einmalig)

1. uniGPT-Schlüssel in der `.env` im Wurzelverzeichnis (`LLM_API_KEY`), siehe
   `ai-agents/README.md`, Abschnitt „uniGPT anbinden“.
2. Im Ordner `ai-agents/`: `python -m venv .venv`, aktivieren,
   `pip install -e ".[dev]"`.

## Vorführung ohne Docker

Im Ordner `ai-agents/`:

```bash
python demo/run_demo.py               # drei Beispielfragen, ca. 15 s
python demo/run_demo.py --dialog      # eigene Fragen, Folgefragen merken sich den Verlauf
python demo/run_demo.py --testfragen  # alle 15 Testfragen mit Bewertung, ca. 1 min
```

Das Skript startet den Demo-Katalog (6 Beispieldatensätze, Port 8081) und den
Agenten (Port 8000), stellt die Fragen und beendet beides wieder.

## Was man sieht

| Zeile im Terminal | Bedeutung |
| --- | --- |
| `… Durchsuche den Katalog …` | Statusmeldung, kommt nach weniger als 1 s |
| `STAC-Anfrage: GET …/collections?q=PM2.5&bbox=…&datetime=…` | die Anfrage, die DeepSeek selbst gebaut hat |
| `Treffer: eea-pm25-annual-mean – …` | was der Katalog geliefert hat |
| `Antwort: …` | die Antwort, Wort für Wort gestreamt |
| `✓ Grounding: … belegt` | jeder genannte Datensatz stammt aus dem Katalog |

Gute Fragen für die Vorführung:

- „Welche Datensätze zeigen PM2.5 in NRW für 2020–2023?“: Ort und Zeitraum werden zur Suchanfrage.
- „Gibt es Daten zur hausärztlichen Versorgung?“: thematische Suche.
- „Gibt es Daten zu Masernfällen in Bayern?“: Fallenfrage; der Agent sagt ehrlich, dass es nichts gibt.
- Im Dialog nach der PM2.5-Frage: „Und nur für 2022?“: Folgefrage mit Verlauf.

## Mit dem echten Katalog

Läuft der Katalog-Stack aus `docker/` (stac-api auf Port 8080) und sind dort
Collections geladen, nutzt die Demo ihn statt des Demo-Katalogs:

```bash
python demo/run_demo.py --stac-url http://localhost:8080
```

Der Demo-Katalog ist nur ein Stellvertreter für Vorführung und Tests. Katalog,
Ingest und die Einbindung des Agenten in Docker Compose gehören zu den
Komponenten von Khang, Paul und Lukas. Für den Agenten liegt ein `Dockerfile`
in `ai-agents/` bereit.
