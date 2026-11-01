"""Measure extraction and the exception agent on the golden set, check the gates, and write evals/REPORT.md and
evals/results.json. A plain script, not part of the test suite.

  uv run python evals/run.py                  # dev split, replaying recorded model answers (no Ollama needed)
  uv run python evals/run.py --live           # dev split against Ollama, recording every answer
  uv run python evals/run.py --split test     # the held-out test split (make eval-test)
  uv run python evals/run.py --baseline evals/baseline.json   # also fail on a drop of more than 1.5 points

Exits 1 if a gate is missed (or a baseline metric drops). Results per case are cached by (model, prompt version,
case) in evals/cache/, so a rerun or an interrupted live run picks up where it stopped; --fresh ignores the cache.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS.parent))  # `python evals/run.py` from the repo root imports the evals package

from evals import agent_db, metrics  # noqa: E402
from evals.replay import MissingRecording, Recorder, current_case  # noqa: E402
from ledgerline_api import agent, jobs, prompts  # noqa: E402
from ledgerline_api.db import AgentRun, AgentStep, PendingAction  # noqa: E402
from ledgerline_api.errors import PermanentError, TransientError  # noqa: E402
from ledgerline_api.settings import settings  # noqa: E402

GOLDEN = EVALS / "golden"
SPLIT_SIZES = {"extraction": 20, "agent": 10}  # how many cases are held out for the test split
# Quality gates, set from the first baseline (docs/metrics.md, slice 6a). Speed is reported but not gated: it
# depends on the machine, and the eval is for comparing models and runs, not for policing this laptop.
GATES = {  # metric: (direction, threshold)
    "header_macro_accuracy": (">=", 0.97), "header_min_field_accuracy": (">=", 0.93), "line_f1": (">=", 0.95),
    "schema_validity": (">=", 0.98), "calibration_error": ("<=", 0.02), "agent_action_accuracy": (">=", 0.85),
}
# Metrics a baseline protects: a drop of more than 1.5 points (0.015) fails the run.
BASELINE_METRICS = ["header_macro_accuracy", "line_f1", "schema_validity", "agent_action_accuracy"]
CONFIDENCE_KEY = {"subtotal_minor": "subtotal", "tax_minor": "tax", "total_minor": "total"}


def split(ids: list[str], kind: str, which: str) -> list[str]:
    """Fixed split: cases sorted by a hash of their id; the first N are the test split. Adding a case never moves
    an existing one between splits unless it lands among the first N."""
    ordered = sorted(ids, key=lambda i: hashlib.sha256(f"{kind}/{i}".encode()).hexdigest())
    test = set(ordered[:SPLIT_SIZES[kind]])
    return sorted(i for i in ids if (i in test) == (which == "test"))


@contextlib.asynccontextmanager
async def no_slot(_redis=None):
    yield


# --- running -----------------------------------------------------------------------------------------------

def cache_path(kind: str, version: str, case: str) -> Path:
    return EVALS / "cache" / settings.llm_model.replace(":", "_") / version.replace("/", "_") / kind / f"{case}.json"


async def extract_case(case: str, recorder: Recorder) -> dict:
    token = current_case.set(case)
    started = time.perf_counter()
    try:
        content = (GOLDEN / "extraction" / f"{case}.pdf").read_bytes()
        try:
            result = await jobs._extract_document(content, redis_client=None)
        except TransientError:
            # A model timeout, as the worker would see under memory pressure: one retry, like the job queue's.
            recorder.stats.pop(case, None)
            result = await jobs._extract_document(content, redis_client=None)
        header = asdict(result.header)
        out = {
            "status": result.status, "repair_attempted": result.repair_attempted, "prompt_version": result.prompt_version,
            "header": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in header.items() if k not in ("field_confidence", "invalid_fields")},
            "confidence": header["field_confidence"], "invalid_fields": header["invalid_fields"],
            "lines": [{"description": l.description, "quantity": None if l.quantity is None else str(l.quantity),
                       "unit_price": None if l.unit_price is None else str(l.unit_price), "amount_minor": l.amount_minor} for l in result.lines],
            "pages": [{"page_no": p.page_no, "status": p.status, "source": p.source, "error_code": p.error_code} for p in result.pages],
        }
    except (PermanentError, TransientError) as exc:  # still failing after the retry: scored as a failed invoice
        out = {"status": "failed", "error": exc.code, "detail": exc.detail, "header": {}, "confidence": {}, "lines": [], "pages": []}
    finally:
        current_case.reset(token)
    out["calls"] = recorder.stats.pop(case, [])
    out["wall_s"] = round(time.perf_counter() - started, 2)
    return out


async def agent_case(scenario: dict, recorder: Recorder) -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    invoice_id = await agent_db.seed(scenario)
    token = current_case.set(scenario["id"])
    try:
        try:
            outcome = await agent.run(invoice_id)
        except TransientError:
            recorder.stats.pop(scenario["id"], None)
            invoice_id = await agent_db.seed(scenario)  # a fresh start: the failed run left a row behind
            try:
                outcome = await agent.run(invoice_id)
            except TransientError as exc:
                outcome = f"failed: {exc.code}"
    finally:
        current_case.reset(token)
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine)() as session:
        run = (await session.execute(select(AgentRun).where(AgentRun.invoice_id == invoice_id))).scalars().first()
        steps = (await session.execute(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.step_no))).scalars().all() if run else []
        action = (await session.execute(select(PendingAction).where(PendingAction.invoice_id == invoice_id))).scalars().first()
    await engine.dispose()
    return {
        "outcome": outcome, "stop_reason": run.stop_reason if run else None, "tool_turns": run.tool_turns if run else 0,
        "guard_fires": run.guard_fires if run else 0,
        "action_type": action.action_type if action else None, "details": action.details if action else None,
        "tools_ok": [s.tool_name for s in steps if s.kind == "tool" and not s.error],
        "tool_errors": [{"tool": s.tool_name, "error": s.error} for s in steps if s.kind == "tool" and s.error],
        "calls": recorder.stats.pop(scenario["id"], []),
    }


async def run_all(cases: list[str], scenarios: list[dict], recorder: Recorder, fresh: bool, concurrency: int) -> tuple[dict, dict]:
    extraction_version = f"{prompts.EXTRACT_PAGE_VERSION}+{prompts.REPAIR_VERSION}"
    results: dict[str, dict] = {}
    gate = asyncio.Semaphore(concurrency)

    async def one(case: str):
        path = cache_path("extraction", extraction_version, case)
        if path.exists() and not fresh:
            results[case] = json.loads(path.read_text())
            return
        async with gate:
            results[case] = await extract_case(case, recorder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results[case], indent=1))
        print(f"  extraction {case}: {results[case]['status']} ({sum(c['ms'] for c in results[case]['calls']) / 1000:.1f}s model)", flush=True)

    await asyncio.gather(*(one(c) for c in cases))

    agent_results: dict[str, dict] = {}
    for s in scenarios:
        path = cache_path("agent", prompts.AGENT_VERSION, s["id"])
        if path.exists() and not fresh:
            agent_results[s["id"]] = json.loads(path.read_text())
            continue
        # One at a time: each scenario empties and reseeds the database.
        agent_results[s["id"]] = await agent_case(s, recorder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(agent_results[s["id"]], indent=1, default=str))
        print(f"  agent {s['id']}: {agent_results[s['id']]['action_type']} ({sum(c['ms'] for c in agent_results[s['id']]['calls']) / 1000:.1f}s model)", flush=True)
    return results, agent_results


# --- scoring -----------------------------------------------------------------------------------------------

def score(golds: dict[str, dict], results: dict[str, dict], scenarios: list[dict], agent_results: dict[str, dict], concurrency: int) -> dict:
    per_field = {f: [] for f in metrics.HEADER_FIELDS}
    observations, tp, predicted, gold_lines, failures = [], 0, 0, 0, []
    pages_attempted = pages_invalid = 0
    latencies, page_latencies, out_tokens, out_ms, statuses_ok = [], [], 0, 0.0, 0
    for case, gold in sorted(golds.items()):
        got = results[case]
        correct = metrics.header_correct(gold, got["header"])
        for field, ok in correct.items():
            per_field[field].append(ok)
            confidence = got["confidence"].get(CONFIDENCE_KEY.get(field, field))
            if confidence is not None:
                observations.append((confidence, ok))
        lines = metrics.match_lines(gold["lines"], got["lines"])
        tp, predicted, gold_lines = tp + lines.true_positives, predicted + lines.predicted, gold_lines + lines.gold
        attempted = [p for p in got["pages"] if p["status"] != "blank"]
        pages_attempted += len(attempted)
        pages_invalid += sum(1 for p in attempted if p["error_code"] == "invalid_model_output")
        expected_status = "exception" if gold["arithmetic_error"] else "extracted"
        statuses_ok += got["status"] == expected_status
        latencies.append(sum(c["ms"] for c in got["calls"]) / 1000)
        read = sum(1 for p in attempted if p["status"] == "extracted" or p["error_code"] == "invalid_model_output")
        page_latencies += [c["ms"] / 1000 for c in got["calls"][:read]]  # page calls come first; a repair call after
        out_tokens += sum(c["output_tokens"] for c in got["calls"])
        out_ms += sum(c["output_ms"] for c in got["calls"])
        wrong = {f: {"gold": gold.get(f), "got": got["header"].get(f)} for f, ok in correct.items() if not ok}
        bad_lines = [{"gold": gold["lines"][g], "got": got["lines"][p], "similarity": round(sim)} for g, p, sim, ok in lines.pairs if not ok]
        if wrong or bad_lines or lines.predicted != lines.gold or got["status"] != expected_status:
            failures.append({"case": case, "style": gold["style"], "pages": gold["pages"], "status": got["status"], "expected_status": expected_status,
                             "fields": wrong, "lines": bad_lines, "line_counts": [lines.gold, lines.predicted], "error": got.get("error")})
    field_accuracy = {f: sum(v) / len(v) for f, v in per_field.items()}
    calibration, confident_n = metrics.calibration_error(observations)
    mean_latency = sum(latencies) / len(latencies) if latencies else 0

    agent_rows, action_ok, reason_ok, holds, evidence_ok = [], 0, 0, 0, 0
    for s in scenarios:
        got, gold = agent_results[s["id"]], s["gold"]
        ok = got["action_type"] == gold["action"]
        action_ok += ok
        reason = None
        if gold["action"] == "hold":
            holds += 1
            reason = (got.get("details") or {}).get("reason_code")
            reason_ok += ok and reason == gold.get("reason_code")
        evidence = set(gold.get("required_tools", [])) <= set(got["tools_ok"])
        evidence_ok += evidence
        agent_rows.append({"id": s["id"], "gold": gold["action"] + (f" ({gold['reason_code']})" if gold.get("reason_code") else ""),
                           "got": (got["action_type"] or "none") + (f" ({reason})" if reason else ""), "correct": ok, "evidence": evidence,
                           "tools": got["tools_ok"], "guard_fires": got["guard_fires"], "stop": got["stop_reason"],
                           "model_s": round(sum(c["ms"] for c in got["calls"]) / 1000, 1)})
    n = len(scenarios)
    return {
        "header_macro_accuracy": sum(field_accuracy.values()) / len(field_accuracy),
        "header_min_field_accuracy": min(field_accuracy.values()),
        "field_accuracy": field_accuracy,
        "line_precision": tp / predicted if predicted else 0, "line_recall": tp / gold_lines if gold_lines else 0,
        "line_f1": metrics.f1(tp, predicted, gold_lines), "line_counts": {"correct": tp, "predicted": predicted, "gold": gold_lines},
        "schema_validity": 1 - pages_invalid / pages_attempted if pages_attempted else 1.0,
        "calibration_error": calibration, "calibration_n": confident_n,
        "status_accuracy": statuses_ok / len(golds) if golds else 0,
        "extraction_p50_s": metrics.percentile(latencies, 50), "extraction_p95_s": metrics.percentile(latencies, 95),
        "page_p50_s": metrics.percentile(page_latencies, 50), "page_p95_s": metrics.percentile(page_latencies, 95),
        "output_tokens_per_s": out_tokens / (out_ms / 1000) if out_ms else 0,
        "invoices_per_hour": concurrency * 3600 / mean_latency if mean_latency else 0,
        "agent_action_accuracy": action_ok / n if n else 0, "agent_hold_reason_accuracy": reason_ok / holds if holds else 0,
        "agent_evidence_complete": evidence_ok / n if n else 0, "agent_guard_fires": sum(r["guard_fires"] for r in agent_rows),
        "agent_p95_s": metrics.percentile([r["model_s"] for r in agent_rows], 95),
        "failures": failures, "agent_rows": agent_rows,
    }


def check_gates(m: dict, baseline: dict | None) -> list[str]:
    missed = []
    for name, (op, threshold) in GATES.items():
        value = m[name]
        if (op == ">=" and value < threshold) or (op == "<=" and value > threshold):
            missed.append(f"{name} = {value:.3f} (gate {op} {threshold})")
    for name in BASELINE_METRICS if baseline else []:
        if name in baseline and m[name] < baseline[name] - 0.015:
            missed.append(f"{name} dropped from {baseline[name]:.3f} to {m[name]:.3f} (more than 1.5 points)")
    return missed


# --- report ------------------------------------------------------------------------------------------------

def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def write_report(m: dict, run: dict, missed: list[str]) -> str:
    gate_rows = "\n".join(f"| {name} | {pct(m[name])} | {op} {pct(t)} | {'pass' if not any(x.startswith(name + ' ') for x in missed) else '**miss**'} |"
                          for name, (op, t) in GATES.items())
    fields = "\n".join(f"| {f} | {pct(a)} |" for f, a in m["field_accuracy"].items())
    agent_rows = "\n".join(f"| {r['id']} | {r['gold']} | {r['got']} | {'yes' if r['correct'] else '**no**'} | {'yes' if r['evidence'] else 'no'} | "
                           f"{', '.join(r['tools']) or '—'} | {r['model_s']} |" for r in m["agent_rows"])
    failures = []
    for f in m["failures"]:
        parts = [f"**{f['case']}** ({f['style']}, {f['pages']} page{'s' if f['pages'] > 1 else ''}): status {f['status']}"
                 + (f" (expected {f['expected_status']})" if f["status"] != f["expected_status"] else "")]
        if f["error"]:
            parts.append(f"  - error: {f['error']}")
        parts += [f"  - {name}: gold `{v['gold']}`, got `{v['got']}`" for name, v in f["fields"].items()]
        if f["line_counts"][0] != f["line_counts"][1]:
            parts.append(f"  - lines: {f['line_counts'][0]} in gold, {f['line_counts'][1]} extracted")
        parts += [f"  - line `{b['gold']['description']}`: gold {b['gold']['quantity']} × {b['gold']['unit_price']} = {b['gold']['amount_minor']}, "
                  f"got `{b['got']['description']}` {b['got']['quantity']} × {b['got']['unit_price']} = {b['got']['amount_minor']} (similarity {b['similarity']})"
                  for b in f["lines"]]
        failures.append("\n".join(parts))
    lc = m["line_counts"]
    return f"""# Eval report

Model **{run['model']}**, prompts `{run['extraction_prompt']}` and `{run['agent_prompt']}`, **{run['split']}** split
({run['extraction_cases']} invoices, {run['agent_cases']} agent scenarios), {run['mode']} on {run['date']}.
Generated by `evals/run.py`; numbers come from the recorded model answers, so a replay reproduces them exactly.

## Gates

{"All gates pass." if not missed else "Missed: " + "; ".join(missed)}

| Metric | Value | Gate | |
|---|---|---|---|
{gate_rows}

## Extraction

| Header field | Exact match |
|---|---|
{fields}

- Line items: precision {pct(m['line_precision'])}, recall {pct(m['line_recall'])}, F1 **{pct(m['line_f1'])}** ({lc['correct']} correct of {lc['gold']} gold lines, {lc['predicted']} extracted).
- First-try schema validity: {pct(m['schema_validity'])} of pages answered in the required JSON shape.
- Calibration: of {m['calibration_n']} fields the model was at least 90% sure of, {pct(m['calibration_error'])} were wrong.
- Final status as expected (exception for the three misprinted totals, extracted otherwise): {pct(m['status_accuracy'])}.

## Speed (this machine, concurrency {run['concurrency']})

| | |
|---|---|
| Model time per invoice, p50 / p95 | {m['extraction_p50_s']:.1f} s / {m['extraction_p95_s']:.1f} s |
| Model time per page, p50 / p95 | {m['page_p50_s']:.1f} s / {m['page_p95_s']:.1f} s |
| Output tokens per second | {m['output_tokens_per_s']:.1f} |
| Invoices per hour | {m['invoices_per_hour']:.0f} |
| Agent model time per scenario, p95 | {m['agent_p95_s']:.1f} s |

Times are Ollama's own (prompt evaluation plus generation, model loading excluded), summed over an invoice's calls.
Speed is reported, not gated: it depends on the machine. Compare it between models on the same machine.

## Agent

Action accuracy **{pct(m['agent_action_accuracy'])}**; hold reason right for {pct(m['agent_hold_reason_accuracy'])} of holds; required evidence gathered
in {pct(m['agent_evidence_complete'])} of scenarios; {m['agent_guard_fires']} actions refused by the code guard.

| Scenario | Gold | Proposed | Right | Evidence | Tools that succeeded | Model s |
|---|---|---|---|---|---|---|
{agent_rows}

## Extraction failures ({len(m['failures'])} invoices)

{chr(10).join(failures) or "None."}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="call Ollama and record its answers")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--fresh", action="store_true", help="ignore cached results")
    parser.add_argument("--baseline", type=Path, help="fail on a drop of more than 1.5 points against this file")
    parser.add_argument("--write-baseline", type=Path, help="save this run's metrics as a baseline")
    parser.add_argument("--cases", help="comma-separated case ids to run (for debugging; gates still apply)")
    parser.add_argument("--out", type=Path, default=EVALS, help="where REPORT.md and results.json go (the sweep writes one folder per model)")
    args = parser.parse_args()

    concurrency = int(os.environ.get("OLLAMA_NUM_PARALLEL", "1"))
    golds = {p.stem: json.loads(p.read_text()) for p in sorted((GOLDEN / "extraction").glob("*.json"))}
    cases = split(list(golds), "extraction", args.split)
    golds = {c: golds[c] for c in cases}
    all_scenarios = {p.stem: yaml.safe_load(p.read_text()) for p in sorted((GOLDEN / "agent").glob("*.yaml"))}
    scenarios = [all_scenarios[i] for i in split(list(all_scenarios), "agent", args.split)]
    if args.cases:
        wanted = set(args.cases.split(","))
        golds = {c: g for c, g in golds.items() if c in wanted}
        cases, scenarios = list(golds), [s for s in scenarios if s["id"] in wanted]

    jobs.llm_slot = agent.llm_slot = no_slot  # no Redis: the eval's own semaphore caps concurrency
    recorder = Recorder(live=args.live).install()
    print(f"{'live' if args.live else 'replay'}: {len(cases)} invoices, {len(scenarios)} agent scenarios, model {settings.llm_model}", flush=True)
    # The agent's database is started outside the event loop: migrating it runs Alembic, which starts its own loop.
    needs_db = any(args.fresh or not cache_path("agent", prompts.AGENT_VERSION, s["id"]).exists() for s in scenarios)
    container = agent_db.start_database() if needs_db else None
    try:
        results, agent_results = asyncio.run(run_all(cases, scenarios, recorder, args.fresh, concurrency))
    except MissingRecording as exc:
        sys.exit(f"replay failed: {exc}")
    finally:
        recorder.uninstall()
        if container:
            container.stop()

    m = score(golds, results, scenarios, agent_results, concurrency)
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    missed = check_gates(m, baseline)
    run = {"model": settings.llm_model, "extraction_prompt": f"{prompts.EXTRACT_PAGE_VERSION}+{prompts.REPAIR_VERSION}",
           "agent_prompt": prompts.AGENT_VERSION, "split": args.split, "mode": "live" if args.live else "replayed",
           "date": datetime.now(UTC).strftime("%Y-%m-%d"), "extraction_cases": len(cases), "agent_cases": len(scenarios),
           "concurrency": concurrency, "recorded": recorder.recorded, "replayed": recorder.replayed}
    summary = {k: v for k, v in m.items() if k not in ("failures", "agent_rows")}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps({"run": run, "metrics": summary, "failures": m["failures"], "agent": m["agent_rows"]}, indent=2, default=str))
    (args.out / "REPORT.md").write_text(write_report(m, run, missed))
    if args.write_baseline:
        args.write_baseline.write_text(json.dumps({k: summary[k] for k in BASELINE_METRICS} | {"model": run["model"]}, indent=2) + "\n")
    print(f"\nheader macro {pct(m['header_macro_accuracy'])} (min field {pct(m['header_min_field_accuracy'])}), line F1 {pct(m['line_f1'])}, "
          f"schema {pct(m['schema_validity'])}, calibration error {pct(m['calibration_error'])}, agent {pct(m['agent_action_accuracy'])}, "
          f"p95 {m['extraction_p95_s']:.1f}s per invoice ({m['page_p95_s']:.1f}s per page), {m['output_tokens_per_s']:.1f} tok/s, {m['invoices_per_hour']:.0f} invoices/h")
    print("all gates pass" if not missed else "MISSED:\n  " + "\n  ".join(missed))
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
