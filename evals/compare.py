"""The eval's metrics next to the base branch's baseline, as a Markdown table (CI posts it as a sticky PR comment).

  uv run python evals/compare.py evals/results.json main-baseline.json > eval-comment.md
"""

import json
import sys
from pathlib import Path

ROWS = [  # (metric, label, higher is better)
    ("header_macro_accuracy", "Header fields (avg)", True),
    ("header_min_field_accuracy", "Lowest header field", True),
    ("line_f1", "Line items F1", True),
    ("schema_validity", "First-try schema validity", True),
    ("calibration_error", "Calibration error", False),
    ("agent_action_accuracy", "Agent action accuracy", True),
]
SPEED = [("page_p50_s", "Model time per page, p50"), ("page_p95_s", "Model time per page, p95"),
         ("invoices_per_hour", "Invoices per hour")]


def table(results: dict, baseline: dict) -> str:
    m, run = results["metrics"], results["run"]
    lines = [
        "<!-- ledgerline-eval -->",
        "### Offline eval",
        f"Model `{run['model']}`, prompts `{run['extraction_prompt']}` and `{run['agent_prompt']}`, {run['split']} split, "
        f"replayed from recorded answers. Compared with `evals/baseline.json` on the base branch.",
        "",
        "| Metric | This PR | Base | Change |",
        "|---|---|---|---|",
    ]
    for key, label, higher in ROWS:
        now, base = m.get(key), baseline.get(key)
        if now is None:
            continue
        change = "—" if base is None else f"{(now - base) * 100:+.1f} pts"
        if base is not None and abs(now - base) >= 0.0005:
            change += " ✅" if (now > base) == higher else " ⚠️"
        lines.append(f"| {label} | {now * 100:.1f}% | {'—' if base is None else f'{base * 100:.1f}%'} | {change} |")
    lines += ["", "Speed comes from the recorded answers (reported, not gated):", ""]
    lines += [f"- {label}: {m[key]:.1f}" + (" s" if key.endswith("_s") else "") for key, label in SPEED if key in m]
    return "\n".join(lines) + "\n"


def main() -> None:
    results = json.loads(Path(sys.argv[1]).read_text())
    baseline = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 and Path(sys.argv[2]).exists() else {}
    sys.stdout.write(table(results, baseline))


if __name__ == "__main__":
    main()
