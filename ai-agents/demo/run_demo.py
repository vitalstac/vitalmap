"""Startet Demo-Katalog und Agenten und stellt Beispielfragen im Terminal.

Voraussetzung: uniGPT-Schlüssel in der ``.env`` (siehe README, „uniGPT anbinden“).

Aufruf (im Ordner ``ai-agents/``)::

    python demo/run_demo.py                 # drei Beispielfragen
    python demo/run_demo.py --dialog        # eigene Fragen eintippen
    python demo/run_demo.py --testfragen    # alle 15 Fragen des Testkatalogs
    python demo/run_demo.py --stac-url http://localhost:8080   # echter Katalog

Ohne ``--stac-url`` startet der Demo-Katalog aus ``demo/collections/`` auf
Port 8081. Beide Server werden am Ende wieder beendet.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = [
    "Welche Datensätze zeigen PM2.5 in NRW für 2020–2023?",
    "Gibt es Daten zur hausärztlichen Versorgung?",
    "Gibt es Daten zu Masernfällen in Bayern?",
]


def wait_for(url: str, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def start(args: list[str], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", *args, "--log-level", "warning"],
        cwd=ROOT,
        env=env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dialog", action="store_true", help="eigene Fragen stellen")
    parser.add_argument(
        "--testfragen", action="store_true", help="Testkatalog auswerten (#8)"
    )
    parser.add_argument("--stac-url", default="", help="echter Katalog statt Demo")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    processes = []
    try:
        if args.stac_url:
            env["STAC_API_URL"] = args.stac_url
        else:
            env["STAC_API_URL"] = "http://127.0.0.1:8081"
            processes.append(start(["demo.stac_demo:app", "--port", "8081"], env))
            if not wait_for("http://127.0.0.1:8081/"):
                print("Demo-Katalog startet nicht.")
                return 1
        port = str(args.port)
        processes.append(start(["vitalmap_agent.api:app", "--port", port], env))
        health = f"http://127.0.0.1:{port}/api/agent/health"
        if not wait_for(health):
            print("Agent startet nicht (uniGPT-Schlüssel in der .env?).")
            return 1
        info = httpx.get(health).json()
        print(
            f"Agent läuft: Modell {info['model']}, Katalog {info['stac_api']}",
            flush=True,
        )

        cli = [sys.executable, "-m", "vitalmap_agent.cli"]
        cli += ["--url", f"http://127.0.0.1:{port}/api/agent/chat"]
        if args.testfragen:
            label = "demo-katalog" if not args.stac_url else "katalog"
            run = [sys.executable, "eval/run_testfragen.py", "--label", label]
            run += ["--url", f"http://127.0.0.1:{port}/api/agent/chat"]
            return subprocess.run(run, cwd=ROOT, env=env).returncode
        if args.dialog:
            subprocess.run(cli, cwd=ROOT, env=env)
        else:
            for question in QUESTIONS:
                subprocess.run([*cli, question], cwd=ROOT, env=env)
        return 0
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
