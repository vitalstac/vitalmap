"""Terminal-Client für den Agenten: zeigt live, was der Agent tut.

Aufruf (Agent muss laufen, z. B. über ``python demo/run_demo.py``)::

    python -m vitalmap_agent.cli "Welche Datensätze zeigen PM2.5 in NRW?"
    python -m vitalmap_agent.cli            # Dialog, Folgefragen in derselben Session

Angezeigt werden die Ereignisse genau so, wie die Web-App sie bekommt:
Statusmeldungen, die ausgeführte STAC-Anfrage mit Treffern, die gestreamte
Antwort und das Ergebnis der Grounding-Prüfung.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import uuid

import httpx

from vitalmap_agent.evaluation.sse import NEUTRAL_CONTEXT, _aparse

DEFAULT_URL = "http://localhost:8000/api/agent/chat"

GREY, CYAN, GREEN, RED, BOLD, RESET = (
    "\033[90m",
    "\033[36m",
    "\033[32m",
    "\033[31m",
    "\033[1m",
    "\033[0m",
)
MARKER_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


def highlight(text: str) -> str:
    return MARKER_RE.sub(lambda m: f"{BOLD}{GREEN}{m.group(1)}{RESET}", text)


async def ask(
    client: httpx.AsyncClient, url: str, session_id: str, question: str, lang: str
) -> None:
    payload = {
        "session_id": session_id,
        "message": question,
        "lang": lang,
        "context": NEUTRAL_CONTEXT,
    }
    start = time.perf_counter()
    first: float | None = None
    streamed = ""
    titles: dict[str, str] = {}
    print(f"\n{BOLD}Frage:{RESET} {question}")
    async with client.stream("POST", url, json=payload) as response:
        response.raise_for_status()
        async for kind, data in _aparse(response.aiter_lines()):
            if first is None:
                first = time.perf_counter() - start
            if kind == "status":
                print(f"{GREY}  … {data.get('message', '')}{RESET}")
            elif kind == "stac_query":
                request = f"{data.get('method')} {data.get('url')}"
                print(f"{CYAN}  STAC-Anfrage: {request}{RESET}")
                hits = data.get("collections", [])
                for hit in hits:
                    titles[hit["id"]] = hit.get("title") or ""
                    print(f"{CYAN}    Treffer: {hit['id']} – {hit.get('title')}{RESET}")
                if not hits:
                    print(f"{CYAN}    keine Treffer{RESET}")
            elif kind == "token":
                if not streamed:
                    print(f"\n{BOLD}Antwort:{RESET} ", end="")
                streamed += data.get("text", "")
                print(data.get("text", ""), end="", flush=True)
            elif kind == "done":
                answer = data.get("answer", "")
                report = data.get("grounding", {})
                if not streamed or answer != streamed:
                    label = "Geprüfte Antwort" if streamed else "Antwort"
                    print(f"\n\n{BOLD}{label}:{RESET} {highlight(answer)}")
                print()
                cited = report.get("citations", [])
                removed = report.get("removed", [])
                print(
                    f"{GREEN}  ✓ Grounding: {len(cited)} Datensatz/-sätze aus dem "
                    f"Katalog belegt{RESET}"
                )
                for cid in cited:
                    print(f"{GREEN}    {cid} – {titles.get(cid, '')}{RESET}")
                if removed:
                    print(f"{RED}  ✗ entfernt (nicht im Katalog): {removed}{RESET}")
            elif kind == "error":
                print(
                    f"\n{RED}  Fehler {data.get('code')}: {data.get('message')}{RESET}"
                )
    total = time.perf_counter() - start
    print(
        f"{GREY}  erste Rückmeldung nach {first or 0:.1f} s, fertig nach "
        f"{total:.1f} s{RESET}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Terminal-Client für den Agenten")
    parser.add_argument("question", nargs="*", help="Frage; leer = Dialog")
    parser.add_argument("--url", default=os.getenv("AGENT_CHAT_URL", DEFAULT_URL))
    parser.add_argument("--lang", default="de", choices=["de", "en"])
    args = parser.parse_args()
    session_id = f"cli-{uuid.uuid4()}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=5.0)) as client:
        try:
            if args.question:
                await ask(
                    client, args.url, session_id, " ".join(args.question), args.lang
                )
                return 0
            print("VitalMap-Agent – Fragen eingeben, leere Zeile beendet.")
            while True:
                question = input(f"\n{BOLD}> {RESET}").strip()
                if not question:
                    return 0
                await ask(client, args.url, session_id, question, args.lang)
        except httpx.ConnectError:
            print(f"{RED}Agent unter {args.url} nicht erreichbar.{RESET}")
            return 1


def run() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if os.name == "nt":
        os.system("")  # ANSI-Farben in der Windows-Konsole einschalten
    raise SystemExit(asyncio.run(main()))


if __name__ == "__main__":
    run()
