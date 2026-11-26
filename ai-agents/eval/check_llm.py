"""Testet die Verbindung zu uniGPT und das Tool-Calling der Modelle (Risiko R3).

Liest LLM_BASE_URL, LLM_MODEL und LLM_API_KEY aus der ``.env`` im
Repository. Für jedes Modell:

1. einfache Antwort mit Streaming, gemessen wird die Zeit bis zum ersten Token,
2. Tool-Calling mit der Beispielfrage aus US-AGT-01.

Aufruf (im Ordner ``ai-agents/``)::

    python eval/check_llm.py               # nur LLM_MODEL (DeepSeek-V4-Flash)
    python eval/check_llm.py --models DeepSeek-V4-Flash,Qwen3.8-27B

Der Bericht landet in ``eval/results/``. Der Schlüssel erscheint nirgends in
der Ausgabe. Exit-Code 0, wenn alle Modelle das Tool korrekt aufrufen.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vitalmap_agent.evaluation.llm_check import (  # noqa: E402
    QUESTION,
    SEARCH_TOOL,
    SYSTEM_PROMPT,
    evaluate_tool_calls,
)
from vitalmap_agent.llm import LLMConfigError, LLMSettings, load_env_file  # noqa: E402

HERE = Path(__file__).resolve().parent


def short_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ")
    return f"{type(exc).__name__}: {text[:200]}"


def key_info(settings: LLMSettings) -> str:
    """Budget und Grenzen des Schlüssels (nur uniGPT)."""
    if settings.is_local:
        return "lokales Modell, kein Budget"
    try:
        response = httpx.get(
            f"{settings.origin}/key/info",
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=15,
        )
        response.raise_for_status()
        info = response.json().get("info", response.json())
    except Exception as exc:  # noqa: BLE001 – nur Diagnose
        return f"nicht abrufbar ({short_error(exc)})"
    keep = (
        "models",
        "max_parallel_requests",
        "rpm_limit",
        "tpm_limit",
        "spend",
        "max_budget",
        "budget_duration",
        "expires",
    )
    return json.dumps({k: info.get(k) for k in keep if k in info}, ensure_ascii=False)


def check_model(settings: LLMSettings) -> dict:
    client = settings.openai_client()
    result: dict = {"model": settings.model}

    # 1) Einfache Antwort mit Streaming
    start = time.perf_counter()
    first = None
    text = ""
    try:
        stream = client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": "Antworte nur mit dem Wort OK."}],
            stream=True,
            max_tokens=200,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            piece = (delta.content or "") if delta else ""
            if piece and first is None:
                first = time.perf_counter() - start
            text += piece
        result["chat"] = "ok" if text.strip() else "leere Antwort"
    except Exception as exc:  # noqa: BLE001
        result["chat"] = short_error(exc)
    result["t_first_token"] = first
    result["t_chat"] = time.perf_counter() - start
    result["answer"] = text.strip()[:60]

    # 2) Tool-Calling
    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=settings.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": QUESTION},
            ],
            tools=[SEARCH_TOOL],
            tool_choice="auto",
            max_tokens=1000,
        )
        calls = response.choices[0].message.tool_calls
        problems = evaluate_tool_calls(calls)
        result["tool_args"] = calls[0].function.arguments if calls else None
    except Exception as exc:  # noqa: BLE001
        problems = [short_error(exc)]
        result["tool_args"] = None
    result["t_tool"] = time.perf_counter() - start
    result["tool_problems"] = problems
    result["passed"] = not problems
    return result


def to_markdown(results: list[dict], settings: LLMSettings, info: str) -> str:
    lines = [
        f"# Verbindungs- und Tool-Calling-Test – {date.today().isoformat()}",
        "",
        f"* Endpunkt: `{settings.base_url}`",
        f"* Schlüssel: {info}",
        f"* Testfrage: „{QUESTION}“",
        "",
        "| Modell | Chat | erstes Token (s) | Tool-Aufruf | Dauer Tool (s) "
        "| Argumente |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        ttft = f"{r['t_first_token']:.1f}" if r["t_first_token"] is not None else "–"
        tool = "bestanden" if r["passed"] else "; ".join(r["tool_problems"])
        args = (r["tool_args"] or "–").replace("|", "/")
        lines.append(
            f"| {r['model']} | {r['chat']} | {ttft} | {tool} | {r['t_tool']:.1f} "
            f"| `{args}` |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", default="", help="kommagetrennte Modell-IDs")
    parser.add_argument("--env", default=None, help="Pfad zur .env")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    env = load_env_file(args.env)
    settings = LLMSettings.from_env()
    try:
        settings.require_key()
    except LLMConfigError as exc:
        print(exc)
        return 2

    models = [m.strip() for m in args.models.split(",") if m.strip()] or [
        settings.model
    ]
    print(f".env: {env or 'keine'} | Endpunkt: {settings.base_url}")
    info = key_info(settings)
    print(f"Schlüssel: {info}")

    results = []
    for model in models:
        print(f"\n[{model}]", flush=True)
        r = check_model(settings.with_model(model))
        results.append(r)
        ttft = f"{r['t_first_token']:.1f} s" if r["t_first_token"] is not None else "–"
        print(
            f"  Chat: {r['chat']} (erstes Token nach {ttft}, Antwort: {r['answer']!r})"
        )
        status = (
            "bestanden"
            if r["passed"]
            else "NICHT bestanden: " + "; ".join(r["tool_problems"])
        )
        print(f"  Tool-Calling: {status} ({r['t_tool']:.1f} s)")
        if r["tool_args"]:
            print(f"  Argumente: {r['tool_args']}")

    if not args.no_report:
        out = HERE / "results" / f"llm-check_{date.today().isoformat()}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(to_markdown(results, settings, info), encoding="utf-8")
        print(f"\nBericht: {out}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
