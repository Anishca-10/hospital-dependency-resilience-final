import pandas as pd

from experiments.demo_trace import run_demo_trace
from experiments.runner import run_suite
from experiments.scenarios import SCENARIOS
from src.database.db import Database
from src.monitoring.metrics import compute_metrics
from src.utils.config_manager import ConfigManager
from tests.conftest import quiet_config


def test_compute_metrics_formulas():
    calls = [dict(operation="o", core_ok=1, status="SUCCESS", latency_ms=100, retry_count=0, fallback_used=0),
             dict(operation="o", core_ok=1, status="DEGRADED", latency_ms=300, retry_count=2, fallback_used=1),
             dict(operation="o", core_ok=0, status="ERROR", latency_ms=500, retry_count=1, fallback_used=0),
             dict(operation="health_check", core_ok=0, status="X", latency_ms=1, retry_count=0, fallback_used=0)]
    m = compute_metrics(calls, [{"result": "TIMEOUT"}, {"result": "SUCCESS"}], [{"new_state": "OPEN"}, {"new_state": "CLOSED"}])
    assert m["total_requests"] == 3 and m["core_availability_pct"] == 66.67 and m["request_success_rate_pct"] == 33.33
    assert m["retry_count"] == 3 and m["fallback_count"] == 1 and m["timeout_count"] == 1 and m["circuit_open_count"] == 1
    assert m["avg_latency_ms"] == 300.0


def test_demo_trace_shows_retry_count_2_circuit_open_fallback_and_recovery():
    rows, events = run_demo_trace(quiet_config())
    assert rows[0]["retry_count"] == 2 and rows[0]["status"] == "RECOVERED"
    assert rows[1]["circuit_state"] == "OPEN" and rows[1]["fallback_used"] and rows[1]["retry_count"] == 2
    assert rows[2]["status"] == "CIRCUIT_OPEN" and rows[3]["status"] == "CIRCUIT_OPEN"
    assert rows[4]["status"] == "RECOVERED" and rows[4]["circuit_state"] == "CLOSED" and rows[5]["status"] == "SUCCESS"
    assert [e["transition"] for e in events] == ["CLOSED -> OPEN", "OPEN -> HALF_OPEN", "HALF_OPEN -> CLOSED"]


def test_suite_is_reproducible_and_fair(tmp_path):
    cm = ConfigManager.from_dict(quiet_config())
    kw = dict(results_dir=str(tmp_path / "r"), figures_dir=str(tmp_path / "f"), reports_dir=str(tmp_path / "d"),
              verbose=False, seeds=[1, 2], visits=30)
    db = Database(str(tmp_path / "e.db"))
    s1 = run_suite(cm, db=db, **kw)
    comp1 = pd.read_csv(tmp_path / "r" / "comparison_results.csv")
    s2 = run_suite(cm, db=None, **kw)
    comp2 = pd.read_csv(tmp_path / "r" / "comparison_results.csv")
    pd.testing.assert_frame_equal(comp1, comp2)                    # same seeds -> identical numbers
    assert s1["baseline_core_availability_pct"] == s2["baseline_core_availability_pct"]
    # availability is computed from logs, not typed in
    b = pd.read_csv(tmp_path / "r" / "baseline_results.csv")
    assert (b["core_availability_pct"] == (100 * b["core_ok_visits"] / b["visits"]).round(2)).all()
    assert s1["resilient_core_availability_pct"] > s1["baseline_core_availability_pct"]
    assert len(comp1) == len(SCENARIOS) >= 6
    for f in ("availability_comparison", "latency_avg_comparison", "latency_p95_comparison", "error_rate_comparison",
              "retry_count_comparison", "circuit_breaker_events", "fallback_usage", "recovery_time_comparison"):
        assert (tmp_path / "f" / f"{f}.png").exists(), f
    assert (tmp_path / "d" / "experiment_report.md").exists()
    runs = db.query("SELECT * FROM experiment_runs")
    assert len(runs) == 2 * len(SCENARIOS) and {r["mode"] for r in runs} == {"baseline", "resilient"}


def test_outage_scenarios_show_resilience_mechanisms(tmp_path):
    cm = ConfigManager.from_dict(quiet_config())
    run_suite(cm, results_dir=str(tmp_path / "r"), figures_dir=str(tmp_path / "f"), reports_dir=str(tmp_path / "d"),
              verbose=False, seeds=[1], visits=40)
    c = pd.read_csv(tmp_path / "r" / "comparison_results.csv").set_index("scenario_id")
    assert c.loc["S1", "baseline_core_availability_pct"] == 100 and c.loc["S1", "resilient_core_availability_pct"] == 100
    assert c.loc["S4", "baseline_core_availability_pct"] < 20 and c.loc["S4", "resilient_core_availability_pct"] == 100
    assert c.loc["S4", "resilient_circuit_open_count"] >= 1 and c.loc["S4", "resilient_fallback_count"] > 0
    assert c.loc["S7", "resilient_retry_count"] > 0                    # transient failures exercise retries
    assert c.loc["S5", "resilient_p95_latency_ms"] < c.loc["S5", "baseline_p95_latency_ms"]   # timeout caps latency
    assert c.loc["S6", "resilient_recovery_time_s"] > 0 and c.loc["S6", "baseline_recovery_time_s"] >= 0
    assert c.loc["S8", "resilient_circuit_open_count"] >= 2             # re-opens after failed HALF_OPEN trials
