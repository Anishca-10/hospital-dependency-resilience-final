"""Baseline vs Resilient experiment runner.

* Same workload, same fault timeline, same seed for both modes. Partner randomness is derived from
  (seed, partner, request key, attempt number), so both systems see identical partner behaviour for
  identical logical requests.
* Executes the REAL application code (HospitalCoreService / ResilienceManager / BaselineClient /
  PartnerSimulator) on a virtual clock, so seconds of simulated latency cost no wall-clock time.
* Every reported number is computed from the recorded call, attempt and circuit-event logs.
"""
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from experiments.demo_trace import run_demo_trace  # noqa: E402
from experiments.scenarios import SCENARIOS  # noqa: E402
from src.core.hospital_service import HospitalCoreService  # noqa: E402
from src.monitoring.metrics import compute_metrics  # noqa: E402
from src.utils.clock import VirtualClock  # noqa: E402
from src.utils.config_manager import ConfigManager  # noqa: E402

MODES = ["baseline", "resilient"]


def run_one(config, scenario, mode, seed, visits, interval_s):
    """One scenario x mode x seed run. Returns raw logs."""
    clock = VirtualClock()
    h = HospitalCoreService(ConfigManager.from_dict(config), db=None, clock=clock, seed=seed,
                            enable_pending_sync=False, source="experiment")
    events_by_visit = {}
    for ev in scenario["events"]:
        events_by_visit.setdefault(ev[0], []).append(ev)
    t0 = clock.time()
    visit_rows, t_recover = [], None
    for i in range(visits):
        clock.advance_to(t0 + i * interval_s)     # visit arrival; if the previous visit ran long we queue
        for (_, partner, action, params) in events_by_visit.get(i, []):
            if action == "set":
                h.simulator.set_mode(partner, params["mode"], params.get("latency_ms"), params.get("error_rate"))
            else:
                h.simulator.recover(partner)
                t_recover = clock.time()
        v = h.run_patient_visit(f"{scenario['id']}-s{seed}-v{i:03d}", f"P-{1001 + i % 24}", mode)
        visit_rows.append(v)
    rec = h.recorder
    calls = [dict(c, scenario_id=scenario["id"], seed=seed) for c in rec.calls()]
    return {"visits": visit_rows, "calls": calls, "attempts": rec.attempts(), "events": rec.circuit_events(),
            "t_recover": t_recover}


def recovery_time_s(calls, partner, t_recover):
    """Seconds from partner recovery to the first fully successful call to that partner."""
    if t_recover is None:
        return None
    later = [c for c in calls if c["partner"] == partner and c["t_end"] is not None and c["t_start"] >= t_recover - 1e-9
             and c["status"] in ("SUCCESS", "RECOVERED")]
    return round(min(c["t_end"] for c in later) - t_recover, 2) if later else None


def aggregate(runs, scenario, slo_s):
    """Pool raw logs of all seeds for one scenario x mode."""
    visits = [v for r in runs for v in r["visits"]]
    calls = [c for r in runs for c in r["calls"]]
    attempts = [a for r in runs for a in r["attempts"]]
    events = [e for r in runs for e in r["events"]]
    m = compute_metrics(calls, attempts, events)
    n = len(visits)
    ok = sum(1 for v in visits if v["core_ok"])
    durs = [v["duration_ms"] for v in visits]
    per_seed = [100.0 * sum(1 for v in r["visits"] if v["core_ok"]) / len(r["visits"]) for r in runs]
    rec = None
    if scenario.get("recovery"):
        vals = [recovery_time_s(r["calls"], scenario["recovery"]["partner"], r["t_recover"]) for r in runs]
        vals = [x for x in vals if x is not None]
        rec = round(float(np.mean(vals)), 2) if vals else None
    return {
        "scenario_id": scenario["id"], "scenario": scenario["name"], "seeds": len(runs), "visits": n,
        "core_ok_visits": ok, "core_availability_pct": round(100.0 * ok / n, 2),
        "availability_std_pp": round(float(np.std(per_seed)), 2),
        "within_slo_pct": round(100.0 * sum(1 for v in visits if v["core_ok"] and v["duration_ms"] <= slo_s * 1000) / n, 2),
        "degraded_visits": sum(1 for v in visits if v["status"] == "COMPLETED_DEGRADED"),
        "avg_visit_ms": round(float(np.mean(durs)), 1), "p95_visit_ms": round(float(np.percentile(durs, 95)), 1),
        "cascading_failures": sum(1 for v in visits if not v["core_ok"]),
        "total_requests": m["total_requests"], "successful_requests": m["successful_requests"],
        "failed_requests": m["failed_requests"], "request_success_rate_pct": m["request_success_rate_pct"],
        "request_failure_rate_pct": m["request_failure_rate_pct"], "errors_propagated_to_core": m["errors_propagated_to_core"],
        "avg_latency_ms": m["avg_latency_ms"], "p95_latency_ms": m["p95_latency_ms"],
        "timeout_count": m["timeout_count"], "retry_count": m["retry_count"], "fallback_count": m["fallback_count"],
        "circuit_open_count": m["circuit_open_count"], "fail_fast_count": m["fail_fast_count"],
        "recovery_time_s": rec,
        "_failed_steps": pd.Series([v["failed_step"] for v in visits if v["failed_step"]]).value_counts().to_dict(),
        "_status_counts": m["status_counts"],
        "_error_types": pd.Series([a["result"] for a in attempts if a["result"] != "SUCCESS"]).value_counts().to_dict(),
    }


# ------------------------------------------------------------------------------ charts
def make_charts(comp, figures_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(figures_dir, exist_ok=True)
    labels = [f"{r.scenario_id}\n{r.scenario}" for r in comp.itertuples()]
    x = np.arange(len(comp))
    colors = {"baseline": "#e74c3c", "resilient": "#2ecc71"}

    def grouped(fname, title, ylabel, bcol, rcol, target=None, ylim=None, only_rows=None, fmt="{:.1f}"):
        fig, ax = plt.subplots(figsize=(13, 5.2))
        idx = np.arange(len(comp)) if only_rows is None else np.array(only_rows)
        xs = np.arange(len(idx))
        b = comp[bcol].values[idx].astype(float)
        r = comp[rcol].values[idx].astype(float)
        w = 0.38
        bars1 = ax.bar(xs - w / 2, np.nan_to_num(b), w, label="Baseline", color=colors["baseline"])
        bars2 = ax.bar(xs + w / 2, np.nan_to_num(r), w, label="Resilient", color=colors["resilient"])
        for bars, vals in ((bars1, b), (bars2, r)):
            for bar, v in zip(bars, vals):
                if not np.isnan(v):
                    ax.annotate(fmt.format(v), (bar.get_x() + bar.get_width() / 2, bar.get_height()), ha="center",
                                va="bottom", fontsize=7.5)
        if target is not None:
            ax.axhline(target, color="#f39c12", ls="--", label=f"Target ({target:g})")
        ax.set_xticks(xs)
        ax.set_xticklabels([labels[i] for i in idx], fontsize=7.5)
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(ylabel)
        if ylim:
            ax.set_ylim(*ylim)
        ax.legend()
        ax.grid(axis="y", alpha=.3)
        fig.tight_layout()
        fig.savefig(os.path.join(figures_dir, fname), dpi=150)
        plt.close(fig)

    tgt = float(comp.attrs.get("target", 95.0))
    grouped("availability_comparison.png", "Core-service availability during simulated partner failures",
            "Core availability (% of patient visits completed)", "baseline_core_availability_pct",
            "resilient_core_availability_pct", target=tgt, ylim=(0, 112))
    grouped("latency_avg_comparison.png", "Average partner-request latency", "ms", "baseline_avg_latency_ms",
            "resilient_avg_latency_ms", fmt="{:.0f}")
    grouped("latency_p95_comparison.png", "P95 partner-request latency", "ms", "baseline_p95_latency_ms",
            "resilient_p95_latency_ms", fmt="{:.0f}")
    grouped("error_rate_comparison.png", "Partner-operation failure rate (calls not completed normally)", "% of calls",
            "baseline_request_failure_rate_pct", "resilient_request_failure_rate_pct", ylim=(0, 112))
    grouped("retry_count_comparison.png", "Retries performed (baseline: 1 immediate retry; resilient: bounded back-off)",
            "retries", "baseline_retry_count", "resilient_retry_count", fmt="{:.0f}")
    grouped("fallback_usage.png", "Fallback usage (baseline has no fallback)", "fallback responses",
            "baseline_fallback_count", "resilient_fallback_count", fmt="{:.0f}")
    # circuit breaker events (resilient only)
    fig, ax = plt.subplots(figsize=(13, 5.2))
    w = 0.38
    a = ax.bar(x - w / 2, comp["resilient_circuit_open_count"], w, label="Circuit OPEN events", color="#9b59b6")
    b = ax.bar(x + w / 2, comp["resilient_fail_fast_count"], w, label="Fail-fast rejections", color="#34495e")
    for bars in (a, b):
        for bar in bars:
            ax.annotate(f"{bar.get_height():.0f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()), ha="center", va="bottom", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_title("Circuit breaker activity (resilient mode; baseline has no breaker)", fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=.3); fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, "circuit_breaker_events.png"), dpi=150); plt.close(fig)
    # recovery time (only scenarios with a recovery event)
    rows = [i for i, v in enumerate(comp["resilient_recovery_time_s"]) if pd.notna(v) or pd.notna(comp["baseline_recovery_time_s"].iloc[i])]
    if rows:
        grouped("recovery_time_comparison.png", "Recovery time: partner restored -> first fully successful call",
                "seconds", "baseline_recovery_time_s", "resilient_recovery_time_s", only_rows=rows, fmt="{:.1f}")


# ------------------------------------------------------------------------------ report
def _fmt(v, nd=2):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def write_report(path, summary, comp, base, res, demo_rows, demo_events):
    s = summary
    L = []
    L += ["# Experiment Report (generated)", "",
          f"_Generated {s['timestamp']} by `python scripts/run_all_experiments.py`. Every number below is computed from "
          "the call, retry-attempt and circuit-event logs of the executed simulations; nothing is typed in by hand._", "",
          "## 1. Design", "",
          f"- **Systems compared:** `baseline` (direct call, {s['config']['baseline_timeout_s']} s client timeout, "
          f"{s['config']['baseline_max_retries']} immediate retry, no circuit breaker, no fallback) vs `resilient` "
          f"(per-partner timeouts {s['config']['timeouts']}, up to {s['config']['retry_max_attempts']} retries with "
          f"{s['config']['retry_backoff_s']} s back-off, circuit breaker threshold {s['config']['cb_threshold']} / recovery "
          f"{s['config']['cb_recovery_s']} s, truthful fallbacks).",
          f"- **Workload:** {s['visits_per_scenario']} patient visits per scenario per seed, one visit every "
          f"{s['visit_interval_s']} s; each visit = registration -> appointment -> consultation -> laboratory -> pharmacy -> insurance -> telemedicine.",
          f"- **Repetitions:** {s['n_seeds']} seeds ({s['seeds']}); each scenario x mode = {s['visits_per_scenario'] * s['n_seeds']} visits.",
          "- **Fairness:** identical workload, identical fault timeline (by visit index) and identical per-request partner randomness for both modes (same seed). Background failure rate follows `config.yaml`.",
          "- **Core request** = one patient visit. **Core success** = the visit completed without a partner error reaching the core application (a visit using truthful fallbacks counts as completed but *degraded*).",
          "- **Primary metric:** core-service availability = successful core requests / total core requests x 100.",
          "- **Secondary metrics:** visits completed within the latency SLO, request-level success (full-fidelity partner success), latency, retries, timeouts, circuit events, fallbacks, recovery time.",
          "- **Clock:** virtual clock - the real code paths run, but sleeping is simulated, so results are exactly reproducible.", "",
          "## 2. Target / result / error analysis", "",
          f"| | Core availability |", "|---|---|",
          f"| **Baseline** (measured) | {s['baseline_core_availability_pct']:.2f}% |",
          f"| **Target** | {s['target_core_availability_pct']:.2f}% |",
          f"| **Resilient** (measured) | {s['resilient_core_availability_pct']:.2f}% |",
          f"| **Improvement** | {s['improvement_pp']:.2f} percentage points |",
          f"| **Target** | **{'Achieved' if s['target_achieved'] else 'Not achieved'}** |", "",
          f"Pooled over all {s['n_scenarios']} scenarios and {s['n_seeds']} seeds "
          f"({s['total_visits_per_mode']} visits per mode). The 95% target was fixed before running: a core service that "
          "loses more than 1 visit in 20 because of a *non-critical* partner outage is not meaningfully protected.", "",
          f"Scenarios meeting the target - baseline: {s['baseline_scenarios_meeting_target']}/{s['n_scenarios']}, "
          f"resilient: {s['resilient_scenarios_meeting_target']}/{s['n_scenarios']}.",
          f"Visits completed within the {s['latency_slo_s']} s latency SLO (secondary) - baseline {s['baseline_within_slo_pct']:.2f}%, "
          f"resilient {s['resilient_within_slo_pct']:.2f}%.", "",
          "## 3. Per-scenario results", "",
          "| Scenario | Base avail % | Res avail % | Base within SLO % | Res within SLO % | Base cascading failures | Res cascading failures | Res degraded visits |",
          "|---|---|---|---|---|---|---|---|"]
    for r in comp.itertuples():
        L.append(f"| {r.scenario_id} {r.scenario} | {r.baseline_core_availability_pct:.2f} (+/-{r.baseline_availability_std_pp:.2f}) | "
                 f"{r.resilient_core_availability_pct:.2f} (+/-{r.resilient_availability_std_pp:.2f}) | {r.baseline_within_slo_pct:.2f} | "
                 f"{r.resilient_within_slo_pct:.2f} | {r.baseline_cascading_failures} | {r.resilient_cascading_failures} | {r.resilient_degraded_visits} |")
    L += ["", "(+/- = standard deviation of availability across seeds, in percentage points.)", "",
          "### Latency, retries and circuit activity", "",
          "| Scenario | Base avg ms | Res avg ms | Base p95 ms | Res p95 ms | Base retries | Res retries | Res timeouts | Res fallbacks | Res circuit opens | Res fail-fast | Base/Res recovery s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in comp.itertuples():
        L.append(f"| {r.scenario_id} | {_fmt(r.baseline_avg_latency_ms, 0)} | {_fmt(r.resilient_avg_latency_ms, 0)} | {_fmt(r.baseline_p95_latency_ms, 0)} | "
                 f"{_fmt(r.resilient_p95_latency_ms, 0)} | {r.baseline_retry_count} | {r.resilient_retry_count} | {r.resilient_timeout_count} | "
                 f"{r.resilient_fallback_count} | {r.resilient_circuit_open_count} | {r.resilient_fail_fast_count} | "
                 f"{_fmt(r.baseline_recovery_time_s, 1)} / {_fmt(r.resilient_recovery_time_s, 1)} |")
    L += ["", "Latency columns are per partner request (ms). Recovery time = seconds from partner restoration to the first fully successful call.", "",
          "### Partner-operation quality (full-fidelity success)", "",
          "| Scenario | Base request success % | Res request success % | Res fallback % of requests |", "|---|---|---|---|"]
    for r in comp.itertuples():
        L.append(f"| {r.scenario_id} | {_fmt(r.baseline_request_success_rate_pct)} | {_fmt(r.resilient_request_success_rate_pct)} | "
                 f"{_fmt(100.0 * r.resilient_fallback_count / r.resilient_total_requests)} |")
    L += ["", "Core availability and partner-operation success measure different things: the resilient layer keeps the "
          "*core* running by converting partner failures into truthful degraded outcomes; it does **not** make the partner itself work.", "",
          "## 4. Error analysis (computed from logs)", ""]
    for r in comp.itertuples():
        b = base[r.scenario_id]; rr = res[r.scenario_id]
        L.append(f"**{r.scenario_id} {r.scenario}**")
        if b["_failed_steps"]:
            L.append(f"- Baseline: {b['cascading_failures']} of {b['visits']} visits failed (cascade); failing step: "
                     + ", ".join(f"{k} x{v}" for k, v in b["_failed_steps"].items()) + ". Failed-attempt causes: "
                     + (", ".join(f"{k} x{v}" for k, v in b["_error_types"].items()) or "none") + ".")
        else:
            L.append("- Baseline: no visit failed.")
        L.append(f"- Resilient: {rr['cascading_failures']} failed visits, {rr['degraded_visits']} degraded visits; request outcomes: "
                 + ", ".join(f"{k} x{v}" for k, v in sorted(rr["_status_counts"].items())) + ".")
        notes = []
        if rr["avg_latency_ms"] is not None and b["avg_latency_ms"] is not None and rr["avg_latency_ms"] > b["avg_latency_ms"]:
            notes.append(f"resilient average request latency is HIGHER than baseline ({rr['avg_latency_ms']:.0f} vs {b['avg_latency_ms']:.0f} ms) - retries and back-off cost time before the breaker opens")
        if rr["p95_latency_ms"] is not None and b["p95_latency_ms"] is not None and rr["p95_latency_ms"] > b["p95_latency_ms"]:
            notes.append(f"resilient P95 latency is HIGHER than baseline ({rr['p95_latency_ms']:.0f} vs {b['p95_latency_ms']:.0f} ms)")
        if b["core_availability_pct"] >= rr["core_availability_pct"] and r.scenario_id != "S1":
            notes.append("no availability gain over the baseline in this scenario")
        if rr["request_success_rate_pct"] is not None and b["request_success_rate_pct"] is not None and rr["request_success_rate_pct"] < b["request_success_rate_pct"]:
            notes.append(f"resilient full-fidelity success is LOWER ({rr['request_success_rate_pct']:.1f}% vs {b['request_success_rate_pct']:.1f}%) because slow-but-valid or flaky responses are cut off by timeouts/breaker and replaced by fallbacks")
        if rr["recovery_time_s"] is not None and b["recovery_time_s"] is not None and rr["recovery_time_s"] > b["recovery_time_s"]:
            notes.append(f"after the partner was restored, the resilient system needed {rr['recovery_time_s']:.1f} s to resume full service vs {b['recovery_time_s']:.1f} s for the baseline (the breaker waits for its recovery timeout before testing the partner) - the price of protection")
        if notes:
            L.append("- Observations: " + "; ".join(notes) + ".")
        L.append("")
    L += ["## 5. Retry and circuit-breaker trace (scripted, deterministic)", "",
          "| Step | Request | Partner | t (s) | Attempts | Retry count | Status | Fallback | Circuit | Latency ms |", "|---|---|---|---|---|---|---|---|---|---|"]
    for d in demo_rows:
        L.append(f"| {d['step']} | {d['request_id']} | {d['partner']} | {d['t_s']} | {d['attempts']} | {d['retry_count']} | {d['status']} | "
                 f"{'yes' if d['fallback_used'] else 'no'} | {d['circuit_state']} | {d['latency_ms']:.0f} |")
    L += ["", "Circuit transitions: " + "; ".join(f"t={e['t_s']}s {e['partner']} {e['transition']} ({e['reason']})" for e in demo_events) + ".", "",
          "## 6. Threats to validity / limitations", "",
          "- Partners are simulators with parametric failure models, not real laboratory/pharmacy/insurance/telemedicine systems.",
          "- Visits are processed sequentially (no concurrency or queueing contention).",
          "- A visit is counted as completed when it finishes with truthful fallbacks; this is a design decision (partners are non-critical to the core workflow) and is reported alongside the full-fidelity request success rate.",
          "- Baseline and resilient parameters come from `config.yaml`; different timeouts/retry settings would change the numbers (use the Configuration page and re-run).",
          "- Synthetic data only; not a clinical or regulatory evaluation."]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ------------------------------------------------------------------------------ suite
def run_suite(config_manager, db=None, results_dir="data/results", figures_dir="outputs/figures",
              reports_dir="docs", verbose=True, scenarios=None, seeds=None, visits=None):
    config = config_manager.get()
    ex = config["experiments"]
    seeds = seeds or ex["seeds"]
    visits = visits or ex["visits_per_scenario"]
    interval = ex["visit_interval_seconds"]
    slo = ex["latency_slo_seconds"]
    target = float(ex["target_core_availability_pct"])
    scenarios = scenarios or SCENARIOS
    for d in (results_dir, figures_dir, reports_dir):
        os.makedirs(d, exist_ok=True)
    exp_id = "EXP-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    agg = {m: {} for m in MODES}
    first_seed_calls = []
    for sc in scenarios:
        for mode in MODES:
            runs = [run_one(config, sc, mode, seed, visits, interval) for seed in seeds]
            agg[mode][sc["id"]] = aggregate(runs, sc, slo)
            first_seed_calls += [{**c, "mode": mode} for c in runs[0]["calls"]]
        if verbose:
            b, r = agg["baseline"][sc["id"]], agg["resilient"][sc["id"]]
            print(f"  {sc['id']} {sc['name']:<34} baseline {b['core_availability_pct']:6.2f}%   resilient {r['core_availability_pct']:6.2f}%")

    def frame(mode):
        return pd.DataFrame([{k: v for k, v in row.items() if not k.startswith("_")} for row in agg[mode].values()])
    bdf, rdf = frame("baseline"), frame("resilient")
    bdf.insert(2, "mode", "baseline"); rdf.insert(2, "mode", "resilient")
    bdf.to_csv(os.path.join(results_dir, "baseline_results.csv"), index=False)
    rdf.to_csv(os.path.join(results_dir, "resilient_results.csv"), index=False)
    comp = bdf.drop(columns="mode").merge(rdf.drop(columns=["mode", "scenario", "seeds", "visits"]), on="scenario_id",
                                          suffixes=("_b", "_r"))
    comp = pd.DataFrame({"scenario_id": bdf["scenario_id"], "scenario": bdf["scenario"],
                         **{f"baseline_{c}": bdf[c].values for c in bdf.columns if c not in ("scenario_id", "scenario", "mode", "seeds", "visits")},
                         **{f"resilient_{c}": rdf[c].values for c in rdf.columns if c not in ("scenario_id", "scenario", "mode", "seeds", "visits")}})
    comp["availability_improvement_pp"] = (comp["resilient_core_availability_pct"] - comp["baseline_core_availability_pct"]).round(2)
    comp.attrs["target"] = target
    comp.to_csv(os.path.join(results_dir, "comparison_results.csv"), index=False)
    pd.DataFrame(first_seed_calls).drop(columns=["source"], errors="ignore").to_csv(
        os.path.join(results_dir, f"experiment_calls_seed{seeds[0]}.csv"), index=False)

    demo_rows, demo_events = run_demo_trace(config)
    pd.DataFrame(demo_rows).to_csv(os.path.join(results_dir, "retry_trace_demo.csv"), index=False)

    def pooled(mode):
        a = agg[mode].values()
        return 100.0 * sum(x["core_ok_visits"] for x in a) / sum(x["visits"] for x in a)

    def pooled_slo(mode):
        a = agg[mode].values()
        return sum(x["within_slo_pct"] * x["visits"] for x in a) / sum(x["visits"] for x in a)
    b_av, r_av = pooled("baseline"), pooled("resilient")
    summary = {
        "experiment_id": exp_id, "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_core_availability_pct": round(b_av, 2), "resilient_core_availability_pct": round(r_av, 2),
        "target_core_availability_pct": target, "improvement_pp": round(r_av - b_av, 2),
        "target_achieved": bool(r_av >= target),
        "baseline_within_slo_pct": round(pooled_slo("baseline"), 2), "resilient_within_slo_pct": round(pooled_slo("resilient"), 2),
        "latency_slo_s": slo,
        "baseline_scenarios_meeting_target": int((comp["baseline_core_availability_pct"] >= target).sum()),
        "resilient_scenarios_meeting_target": int((comp["resilient_core_availability_pct"] >= target).sum()),
        "n_scenarios": len(scenarios), "n_seeds": len(seeds), "seeds": list(seeds), "visits_per_scenario": visits,
        "visit_interval_s": interval, "total_visits_per_mode": int(sum(x["visits"] for x in agg["baseline"].values())),
        "config": {"timeouts": config["resilience"]["timeout"], "retry_max_attempts": config["resilience"]["retry"]["max_attempts"],
                   "retry_backoff_s": config["resilience"]["retry"]["backoff_seconds"],
                   "cb_threshold": config["resilience"]["circuit_breaker"]["failure_threshold"],
                   "cb_recovery_s": config["resilience"]["circuit_breaker"]["recovery_timeout_seconds"],
                   "baseline_timeout_s": config["baseline"]["timeout_seconds"], "baseline_max_retries": config["baseline"]["max_retries"]},
    }
    with open(os.path.join(results_dir, "experiment_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    make_charts(comp, figures_dir)
    write_report(os.path.join(reports_dir, "experiment_report.md"), summary, comp, agg["baseline"], agg["resilient"],
                 demo_rows, demo_events)
    if db is not None:
        ts = dt.datetime.now().isoformat(timespec="seconds")
        for mode in MODES:
            for sc in scenarios:
                x = agg[mode][sc["id"]]
                db.execute("INSERT INTO experiment_runs(experiment_id,timestamp,mode,scenario,total_requests,successful_requests,"
                           "failed_requests,availability,average_latency,p95_latency,retry_count,fallback_count,circuit_open_count,recovery_time)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (exp_id, ts, mode, f"{sc['id']} {sc['name']}", x["visits"], x["core_ok_visits"],
                            x["visits"] - x["core_ok_visits"], x["core_availability_pct"], x["avg_latency_ms"], x["p95_latency_ms"],
                            x["retry_count"], x["fallback_count"], x["circuit_open_count"], x["recovery_time_s"]))
    if verbose:
        print(f"\n  Baseline  : {b_av:.2f}%\n  Target    : {target:.2f}%\n  Resilient : {r_av:.2f}%\n  Improvement: {r_av - b_av:.2f} pp"
              f"\n  Target {'ACHIEVED' if summary['target_achieved'] else 'NOT ACHIEVED'}")
    return summary
