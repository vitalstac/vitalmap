"""Stellt die 15 Testfragen an den laufenden Agenten und bewertet die Antworten.

Voraussetzung: ``docker compose up`` läuft (Agent, STAC API, Geocoder-Zugang).

Aufruf (im Ordner ``ai-agents/``)::

    python eval/run_testfragen.py --label unigpt-deepseek
    python eval/run_testfragen.py --only K1,F2          # nur einzelne Fragen

Ergebnis:

* Bericht als Markdown und JSON in ``eval/results/`` (Pflichtenheft 5.4:
  „Ergebnisse im Repository“).
* Exit-Code 0, wenn das Abnahmekriterium erfüllt ist (>= 12 von 15 richtig und
  alle Fallenfragen bestanden), sonst 1. So lässt sich das Skript vor jedem
  Meilenstein auch in einem CI-Job nutzen.

Die Fragen laufen nacheinander, nicht parallel: So bleibt Nominatim bei
1 Anfrage/s, und die gemessenen Zeiten sind nicht durch Parallelität verfälscht.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

# Damit das Skript ohne Installation des Pakets aus dem Repository läuft.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vitalmap_agent.evaluation.catalog import load_catalog  # noqa: E402
from vitalmap_agent.evaluation.checks import (  # noqa: E402
    evaluate_case,
    summarize,
    to_markdown,
)
from vitalmap_agent.evaluation.sse import stream_agent  # noqa: E402

HERE = Path(__file__).resolve().parent


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=os.getenv("AGENT_CHAT_URL", "http://localhost:8000/api/agent/chat"),
        help="SSE-Endpunkt des Agenten (Standard: $AGENT_CHAT_URL)",
    )
    parser.add_argument("--catalog", default=str(HERE / "testfragen.yaml"))
    parser.add_argument(
        "--label", default="lauf", help="z. B. Modellname für den Dateinamen"
    )
    parser.add_argument("--only", default="", help="kommagetrennte Frage-IDs")
    parser.add_argument("--timeout", type=float, default=65.0, help="Sekunden je Frage")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    questions = [q for q in catalog.questions if not only or q["id"] in only]

    results = []
    for case in questions:
        print(f"[{case['id']}] {case['frage']}", flush=True)
        run = await stream_agent(args.url, case["frage"], timeout_s=args.timeout)
        result = evaluate_case(case, run, catalog.known_ids, catalog.places)
        results.append(result)
        status = (
            "bestanden"
            if result.passed
            else "NICHT bestanden: " + "; ".join(result.reasons)
        )
        print(f"      -> {status}", flush=True)

    summary = summarize(results, catalog.min_passed)
    stem = f"testfragen_{date.today().isoformat()}_{args.label}"
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    title = f"Testfragenkatalog – {date.today().isoformat()} – {args.label}"
    (out_dir / f"{stem}.md").write_text(
        to_markdown(results, summary, title), encoding="utf-8"
    )
    (out_dir / f"{stem}.json").write_text(
        json.dumps([r.as_dict() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"\n{summary.passed}/{summary.total} richtig, Fallen {summary.traps_passed}/"
        f"{summary.traps_total} -> Abnahme "
        f"{'erfüllt' if summary.accepted else 'NICHT erfüllt'}"
    )
    print(f"Bericht: {out_dir / (stem + '.md')}")
    # Bei --only ist das Kriterium nicht sinnvoll; dann nur Fehlschläge zählen.
    if only:
        return 0 if all(r.passed for r in results) else 1
    return 0 if summary.accepted else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
