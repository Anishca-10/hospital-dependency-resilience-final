"""Fill document templates with MEASURED results (data/results/*) and regenerate the feedback summary.

Templates live in docs/_templates/*.tpl and use {{placeholders}}. Numbers are never typed into prose.
Run automatically at the end of scripts/run_all_experiments.py, or manually:  python scripts/generate_docs.py
"""
import json
import os
import re
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

OUTPUTS = {  # template -> output path
    "README.md.tpl": "README.md",
    "project_report.md.tpl": "docs/project_report.md",
    "failure_mode_analysis.md.tpl": "docs/failure_mode_analysis.md",
    "presentation_outline.md.tpl": "presentation/presentation_outline.md",
}


def _fmt(v):
    if isinstance(v, bool):
        return "Achieved" if v else "Not achieved"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def build_context(results_dir):
    with open(os.path.join(results_dir, "experiment_summary.json"), encoding="utf-8") as fh:
        s = json.load(fh)
    ctx = {k: v for k, v in s.items() if not isinstance(v, (dict, list))}
    ctx["target_status"] = "Achieved" if s["target_achieved"] else "Not achieved"
    comp = pd.read_csv(os.path.join(results_dir, "comparison_results.csv"))
    for r in comp.to_dict(orient="records"):
        for k, v in r.items():
            ctx[f"{r['scenario_id']}.{k}"] = "n/a" if pd.isna(v) else v
    hdr = "| Scenario | Baseline avail. % | Resilient avail. % | Improvement (pp) | Baseline p95 ms | Resilient p95 ms | Retries (res.) | Fallbacks (res.) | Circuit opens (res.) |\n|---|---|---|---|---|---|---|---|---|\n"
    ctx["scenario_table"] = hdr + "\n".join(
        f"| {r.scenario_id} {r.scenario} | {r.baseline_core_availability_pct:.2f} | {r.resilient_core_availability_pct:.2f} | "
        f"{r.availability_improvement_pp:.2f} | {r.baseline_p95_latency_ms:.0f} | {r.resilient_p95_latency_ms:.0f} | "
        f"{r.resilient_retry_count} | {r.resilient_fallback_count} | {r.resilient_circuit_open_count} |" for r in comp.itertuples())
    trace = pd.read_csv(os.path.join(results_dir, "retry_trace_demo.csv"))
    ctx["trace_table"] = "| Step | Attempts | Retry count | Status | Circuit |\n|---|---|---|---|---|\n" + "\n".join(
        f"| {r.step} | {r.attempts} | {r.retry_count} | {r.status} | {r.circuit_state} |" for r in trace.itertuples())
    ctx["seeds"] = ", ".join(str(x) for x in s["seeds"])
    ctx["timeouts"] = ", ".join(f"{k} {v}s" for k, v in s["config"]["timeouts"].items())
    for k, v in s["config"].items():
        if not isinstance(v, dict):
            ctx[f"cfg_{k}"] = v
    n_tests = os.environ.get("TEST_COUNT")
    ctx["test_count"] = n_tests or "see `pytest -q`"
    return ctx


def render(text, ctx):
    missing = []

    def sub(m):
        key = m.group(1)
        if key not in ctx:
            missing.append(key)
            return m.group(0)
        return _fmt(ctx[key])
    out = re.sub(r"\{\{([A-Za-z0-9_.]+)\}\}", sub, text)
    if missing:
        raise KeyError(f"Unresolved placeholders: {sorted(set(missing))}")
    return out


def main(results_dir=None):
    results_dir = results_dir or os.path.join(ROOT, "data", "results")
    ctx = build_context(results_dir)
    for tpl, out in OUTPUTS.items():
        with open(os.path.join(ROOT, "docs", "_templates", tpl), encoding="utf-8") as fh:
            text = render(fh.read(), ctx)
        with open(os.path.join(ROOT, out), "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"  generated {out}")
    from src.database.db import Database
    from src.utils import validation_survey as survey
    db = Database(os.path.join(ROOT, "data", "hospital_resilience.db"))
    with open(os.path.join(ROOT, "docs", "user_feedback_summary.md"), "w", encoding="utf-8") as fh:
        fh.write(survey.render_summary_md(db))
    print("  generated docs/user_feedback_summary.md")


if __name__ == "__main__":
    main()
