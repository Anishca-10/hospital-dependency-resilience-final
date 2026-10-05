import pytest

from src.baseline.baseline_client import BaselineClient
from src.resilience.circuit_breaker import CircuitBreaker, CircuitState
from src.resilience.errors import classify
from src.resilience.resilience_manager import ResilienceManager
from src.resilience.retry import RetryPolicy

PAY = {"patient_id": "P-1"}


def make(cfg, clock, sim):
    ev = []
    rm = ResilienceManager(cfg, clock, sim.call, lambda *a: ev.append((a[1], a[2])))
    return rm, ev


def test_classification():
    assert classify(200)[0] == "SUCCESS"
    assert classify(503)[0] == classify(502)[0] == classify(504)[0] == "TRANSIENT"
    assert classify(timed_out=True) == ("TRANSIENT", "TIMEOUT")
    assert classify(400)[0] == classify(401)[0] == "PERMANENT"


def test_retry_policy_bounds():
    p = RetryPolicy(True, 2, 0.2, 2.0)
    assert p.delay_before(1) == pytest.approx(0.2) and p.delay_before(2) == pytest.approx(0.4)
    assert p.may_retry("TRANSIENT", 1) and not p.may_retry("TRANSIENT", 2)
    assert not p.may_retry("PERMANENT", 0) and not RetryPolicy(False, 2, .2, 2).may_retry("TRANSIENT", 0)


def test_timeout_then_retry_then_success_records_retry_count_2(cfg, clock, sim):
    rm, _ = make(cfg, clock, sim)
    sim.script("insurance", ["TIMEOUT", "TIMEOUT", "OK"])
    r = rm.execute("insurance", "verify_eligibility", PAY, "REQ001")
    assert r["retry_count"] == 2 and r["status"] == "RECOVERED" and r["success"] and not r["fallback_used"]
    assert [a["result"] for a in r["attempts"]] == ["TIMEOUT", "TIMEOUT", "SUCCESS"]
    assert [a["outcome"] for a in r["attempts"]] == ["RETRYING", "RETRYING", "SUCCESS"]


def test_timeout_comes_from_config_and_bounds_latency(cfg, clock, sim):
    cfg["resilience"]["timeout"]["telemedicine"] = 1.5
    cfg["resilience"]["retry"]["enabled"] = False
    rm, _ = make(cfg, clock, sim)
    sim.set_mode("telemedicine", "TIMEOUT")
    r = rm.execute("telemedicine", "book_consult", PAY, "R")
    assert r["status"] == "TIMEOUT" and r["fallback_used"] and r["latency_ms"] == pytest.approx(1500, abs=1)


def test_retry_limit_is_respected(cfg, clock, sim):
    cfg["resilience"]["circuit_breaker"]["failure_threshold"] = 20
    rm, _ = make(cfg, clock, sim)
    sim.set_mode("laboratory", "CONTINUOUS_FAILURE")
    r = rm.execute("laboratory", "order_test", PAY, "R")
    assert r["retry_count"] == 2 and r["attempt_count"] == 3 and r["fallback_used"]


def test_permanent_error_not_retried_and_no_fallback_and_no_breaker_penalty(cfg, clock, sim):
    rm, _ = make(cfg, clock, sim)
    for i in range(5):
        r = rm.execute("laboratory", "order_test", {}, f"R{i}")   # missing patient_id -> 400
        assert r["status"] == "REJECTED" and r["retry_count"] == 0 and not r["fallback_used"] and not r["success"]
    assert rm.breakers["laboratory"].state == CircuitState.CLOSED


def test_circuit_closed_to_open_after_threshold_and_fail_fast(cfg, clock, sim):
    rm, ev = make(cfg, clock, sim)
    sim.set_mode("pharmacy", "UNAVAILABLE")
    r1 = rm.execute("pharmacy", "check_prescription", PAY, "R1")     # 3 attempts = 3 failures -> OPEN
    assert r1["circuit_state"] == "OPEN" and ("CLOSED", "OPEN") in ev
    calls_before = sim.states["pharmacy"]["calls"]
    r2 = rm.execute("pharmacy", "check_prescription", PAY, "R2")
    assert r2["status"] == "CIRCUIT_OPEN" and r2["circuit_blocked"] and r2["latency_ms"] == 0
    assert sim.states["pharmacy"]["calls"] == calls_before            # partner NOT contacted


def test_circuit_open_half_open_closed_recovery(cfg, clock, sim):
    rm, ev = make(cfg, clock, sim)
    sim.set_mode("insurance", "UNAVAILABLE")
    rm.execute("insurance", "verify_eligibility", PAY, "R1")
    sim.recover("insurance")
    assert rm.execute("insurance", "verify_eligibility", PAY, "R2")["status"] == "CIRCUIT_OPEN"
    clock.sleep(cfg["resilience"]["circuit_breaker"]["recovery_timeout_seconds"] + 0.1)
    r = rm.execute("insurance", "verify_eligibility", PAY, "R3")
    assert r["status"] == "RECOVERED" and r["circuit_state"] == "CLOSED"
    assert ("OPEN", "HALF_OPEN") in ev and ("HALF_OPEN", "CLOSED") in ev


def test_half_open_failure_reopens(cfg, clock, sim):
    rm, ev = make(cfg, clock, sim)
    sim.set_mode("insurance", "UNAVAILABLE")
    rm.execute("insurance", "verify_eligibility", PAY, "R1")
    clock.sleep(11)
    r = rm.execute("insurance", "verify_eligibility", PAY, "R2")     # trial fails
    assert r["circuit_state"] == "OPEN" and r["fallback_used"] and r["retry_count"] == 0
    assert ("HALF_OPEN", "OPEN") in ev


def test_half_open_limits_trial_calls():
    from src.utils.clock import VirtualClock
    c = VirtualClock()
    cb = CircuitBreaker("x", 1, 5, 1, c)
    cb.record_failure()
    assert cb.state == "OPEN" and not cb.allow_request()
    c.sleep(5)
    assert cb.allow_request() and cb.state == "HALF_OPEN"
    assert not cb.allow_request()          # only half_open_max_calls=1 trial allowed
    cb.record_success()
    assert cb.state == "CLOSED"


def test_fallback_is_truthful_and_uses_configured_text(cfg, clock, sim):
    rm, _ = make(cfg, clock, sim)
    sim.set_mode("insurance", "UNAVAILABLE")
    r = rm.execute("insurance", "verify_eligibility", PAY, "R1")
    assert r["success"] is False and r["fallback_used"] and r["status"] != "SUCCESS"
    assert r["message"] == cfg["fallbacks"]["insurance"]["message"]
    assert r["data"]["eligibility_confirmed"] is False and r["data"]["verification_status"] == "PENDING"
    for p, status_like in [("laboratory", "synchronized"), ("pharmacy", "cannot be refreshed"), ("telemedicine", "try again later")]:
        assert status_like in cfg["fallbacks"][p]["message"]


def test_baseline_has_no_breaker_no_fallback_one_retry(cfg, clock, sim):
    b = BaselineClient(cfg, clock, sim.call)
    sim.set_mode("insurance", "UNAVAILABLE")
    for i in range(6):
        r = b.execute("insurance", "verify_eligibility", PAY, f"R{i}")
        assert r["status"] == "ERROR" and not r["core_ok"] and not r["fallback_used"] and r["retry_count"] == 1
    assert sim.states["insurance"]["calls"] == 12      # keeps hammering the failing partner
    sim.recover("insurance")
    assert b.execute("insurance", "verify_eligibility", PAY, "ok")["status"] == "SUCCESS"


def test_reconfigure_applies_new_rules_in_place(cfg, clock, sim):
    rm, _ = make(cfg, clock, sim)
    cfg["resilience"]["retry"]["max_attempts"] = 0
    cfg["resilience"]["circuit_breaker"]["failure_threshold"] = 1
    rm.reconfigure(cfg)
    sim.set_mode("laboratory", "UNAVAILABLE")
    r = rm.execute("laboratory", "order_test", PAY, "R")
    assert r["retry_count"] == 0 and r["circuit_state"] == "OPEN"
