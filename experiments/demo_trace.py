"""Deterministic retry / circuit-breaker trace (scripted partner outcomes, virtual clock).

Demonstrates, from real execution of the real resilience code:
  Insurance : TIMEOUT, TIMEOUT, SUCCESS      -> retry_count = 2, status RECOVERED
  Laboratory: 3 consecutive failures          -> retries, circuit OPENS, truthful fallback, then fail-fast
  Recovery  : partner recovers, timeout passes -> HALF_OPEN -> trial succeeds -> CLOSED
"""
from src.core.hospital_service import HospitalCoreService
from src.utils.clock import VirtualClock
from src.utils.config_manager import ConfigManager


def run_demo_trace(config: dict):
    cfg = {k: v for k, v in config.items()}
    cfg["partners"] = {p: {**v, "failure_rate": 0.0} for p, v in config["partners"].items()}
    clock = VirtualClock()
    h = HospitalCoreService(ConfigManager.from_dict(cfg), clock=clock, seed=1, source="demo", enable_pending_sync=False)
    rows, t0 = [], clock.time()

    def run(label, partner, req_id):
        r = h.execute_partner(partner, None, {"patient_id": "P-DEMO"}, "resilient", request_id=req_id)
        rows.append({"step": label, "request_id": req_id, "partner": partner, "t_s": round(clock.time() - t0, 2),
                     "attempts": " -> ".join(f"{a['attempt']}:{a['result']}" for a in r["attempts"]) or "none (circuit open)",
                     "retry_count": r["retry_count"], "status": r["status"], "fallback_used": r["fallback_used"],
                     "circuit_state": r["circuit_state"], "latency_ms": r["latency_ms"], "message": r["message"]})
        return r

    h.simulator.script("insurance", ["TIMEOUT", "TIMEOUT", "OK"])
    run("Insurance transient failure (timeout, timeout, success)", "insurance", "REQ001")
    h.simulator.set_mode("laboratory", "CONTINUOUS_FAILURE")
    run("Laboratory failure: retries exhaust, circuit opens, fallback", "laboratory", "REQ002")
    run("Laboratory: circuit OPEN -> fail fast, no partner call", "laboratory", "REQ003")
    h.simulator.recover("laboratory")
    run("Partner recovered, but circuit still OPEN (timeout not elapsed)", "laboratory", "REQ004")
    clock.sleep(h.config["resilience"]["circuit_breaker"]["recovery_timeout_seconds"])
    run("Recovery timeout passed -> HALF_OPEN trial succeeds -> CLOSED", "laboratory", "REQ005")
    run("Normal operation resumed", "laboratory", "REQ006")
    events = [{"t_s": round((e["t"] or t0) - t0, 2), "partner": e["partner"], "transition": f"{e['old_state']} -> {e['new_state']}",
               "reason": e["reason"]} for e in h.recorder.circuit_events()]
    return rows, events
