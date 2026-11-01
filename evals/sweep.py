"""Compare models on the dev split: quality, speed and memory, one row per model, written to evals/SWEEP.md.

Each model runs the same eval (`evals/run.py`) with LLM_MODEL set; its report goes to evals/sweep/<model>/. A model
whose answers are already recorded is replayed; --live reruns them against Ollama. Memory is the resident size
of Ollama's model server process (weights plus the 8k-token context) on a fresh load of the model; --memory remeasures
it without rerunning the eval. Ollama's own /api/ps figure
isn't used: for gemma4:12b it reported 1.0 GB, leaving out the weights. The default model is not changed:
choosing is a decision for a person (see evals/SWEEP.md).

Usage: uv run python evals/sweep.py [--live] [--models gemma4:12b,qwen2.5:7b-instruct,qwen3.5:9b-q4_K_M]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from ledgerline_api.settings import settings

EVALS = Path(__file__).resolve().parent
# llama3.1:8b and qwen2.5:14b-instruct were planned and skipped (the user's call: download size and heat on a 16 GB laptop).
# qwen3.5 pinned to its q4_K_M build: the bare tag downloads different builds on different machines.
MODELS = ["gemma4:12b", "qwen2.5:7b-instruct", "qwen3.5:9b-q4_K_M"]


def folder(model: str) -> Path:
    return EVALS / "sweep" / model.replace(":", "_").replace("/", "_")


def loaded_memory_gb(model: str, ollama: str) -> float | None:
    """Resident memory of Ollama's model server with `model` freshly loaded at the eval's context size.

    Measured on a fresh load (unload, one tiny call, read, unload), not right after a run: after a long run macOS has
    compressed or paged out part of the weights, and the reading wandered by 1.5 GB between runs of the same model.
    """
    def unload() -> None:
        httpx.post(f"{ollama}/api/chat", json={"model": model, "messages": [], "keep_alive": 0}, timeout=60)

    try:
        unload()
        httpx.post(f"{ollama}/api/chat", timeout=300, json={
            "model": model, "messages": [{"role": "user", "content": "hi"}], "stream": False, "think": False,
            "keep_alive": "1m", "options": {"num_ctx": settings.llm_num_ctx, "num_predict": 1}}).raise_for_status()
        ps = subprocess.run(["ps", "-axo", "rss=,command="], capture_output=True, text=True, check=True).stdout
        unload()
    except (httpx.HTTPError, subprocess.CalledProcessError):
        return None
    sizes = [int(line.split(None, 1)[0]) for line in ps.splitlines() if "llama-server" in line or "ollama runner" in line]
    return round(max(sizes) * 1024 / 1e9, 1) if sizes else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="run every model against Ollama, recording answers")
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--memory", action="store_true", help="measure each model's memory again (a fresh load each)")
    args = parser.parse_args()
    ollama = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    rows = []
    for model in args.models.split(","):
        out = folder(model)
        started = time.monotonic()
        live = args.live
        if not live:
            # Replay when every answer is recorded; a model recorded only in part (a trial run) falls back to live,
            # where cached cases are still skipped.
            print(f"== {model}: replay", flush=True)
            replay = subprocess.run([sys.executable, str(EVALS / "run.py"), "--out", str(out)],
                                    env={**os.environ, "LLM_MODEL": model}, capture_output=True, text=True)
            print(replay.stdout[-600:], flush=True)
            live = "replay failed" in replay.stdout + replay.stderr
        if live:
            print(f"== {model}: live", flush=True)
            subprocess.run([sys.executable, str(EVALS / "run.py"), "--out", str(out), "--live"],
                           env={**os.environ, "LLM_MODEL": model}, check=False)
        results = json.loads((out / "results.json").read_text())
        memory = loaded_memory_gb(model, ollama) if live or args.memory else None
        meta_path = out / "sweep.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if memory is not None:
            meta |= {"memory_gb": memory}
        if live:
            meta |= {"wall_minutes": round((time.monotonic() - started) / 60, 1)}
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        rows.append((model, results["metrics"], meta))

    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    table = "\n".join(
        f"| {model} | {pct(m['header_macro_accuracy'])} | {pct(m['header_min_field_accuracy'])} | {pct(m['line_f1'])} | {pct(m['schema_validity'])} | "
        f"{pct(m['calibration_error'])} | {pct(m['agent_action_accuracy'])} | {m['page_p50_s']:.0f} / {m['page_p95_s']:.0f} s | {m['output_tokens_per_s']:.1f} | "
        f"{m['invoices_per_hour']:.0f} | {meta.get('memory_gb', '—')} GB |" for model, m, meta in rows)
    # The recommendation under the marker is written by a person; regenerating the table keeps it.
    marker = "<!-- recommendation -->"
    previous = (EVALS / "SWEEP.md").read_text() if (EVALS / "SWEEP.md").exists() else ""
    kept = previous.split(marker, 1)[1] if marker in previous else "\n"
    (EVALS / "SWEEP.md").write_text(f"""# Model sweep

The dev split (40 invoices, 15 agent scenarios) on each model, same prompts and code. Generated by `evals/sweep.py`;
per-model reports in `evals/sweep/<model>/REPORT.md`. Speed and memory are for this machine (Apple M1 Pro, 16 GB).

| Model | Header avg | Lowest field | Line F1 | Schema valid | Calibration error | Agent | Time per page p50 / p95 | Tokens/s | Invoices/h | Memory |
|---|---|---|---|---|---|---|---|---|---|---|
{table}

{marker}{kept}""")
    print((EVALS / "SWEEP.md").read_text())


if __name__ == "__main__":
    main()
