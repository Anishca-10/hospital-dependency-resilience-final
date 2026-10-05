import pytest

from src.partners.partner_simulator import PartnerSimulator, PartnerTimeout
from src.utils.clock import RealClock, VirtualClock

PAY = {"patient_id": "P-1"}


def test_partner_normal_operation(sim):
    for p, op in [("laboratory", "order_test"), ("pharmacy", "check_prescription"),
                  ("insurance", "verify_eligibility"), ("telemedicine", "book_consult")]:
        r = sim.call(p, op, PAY, 5, f"k-{p}")
        assert r.status_code == 200 and r.body["success"] and r.body["synthetic"] is True


def test_configured_error_rate_100_percent_really_fails(cfg, clock):
    cfg["partners"]["insurance"]["failure_rate"] = 1.0
    s = PartnerSimulator(cfg, clock, seed=1)
    codes = [s.call("insurance", "verify_eligibility", PAY, 5, f"r{i}").status_code for i in range(20)]
    assert all(c in (502, 503, 504) for c in codes)


def test_configured_latency_is_real_elapsed_time(cfg):
    cfg["partners"]["laboratory"]["latency_ms"] = 600
    s = PartnerSimulator(cfg, RealClock(), seed=1)
    import time
    t = time.time()
    s.call("laboratory", "order_test", PAY, 5, "x")
    assert 0.5 < time.time() - t < 0.8


def test_latency_5000ms_on_virtual_clock(cfg, clock):
    cfg["partners"]["laboratory"]["latency_ms"] = 5000
    s = PartnerSimulator(cfg, clock, seed=1)
    t0 = clock.time()
    r = s.call("laboratory", "order_test", PAY, 10, "x")
    assert 4700 <= (clock.time() - t0) * 1000 <= 5300 and 4700 <= r.latency_ms <= 5300


def test_timeout_is_enforced_at_the_deadline(sim, clock):
    sim.set_mode("telemedicine", "TIMEOUT")
    t0 = clock.time()
    with pytest.raises(PartnerTimeout):
        sim.call("telemedicine", "book_consult", PAY, 2.0, "x")
    assert clock.time() - t0 == pytest.approx(2.0)   # returns at the timeout, not after the 30s hang


def test_failure_modes(sim):
    sim.set_mode("pharmacy", "UNAVAILABLE")
    assert sim.call("pharmacy", "check_prescription", PAY, 5, "a").status_code == 503
    sim.set_mode("pharmacy", "CONTINUOUS_FAILURE")
    assert sim.call("pharmacy", "check_prescription", PAY, 5, "b").status_code == 502
    sim.set_mode("pharmacy", "INTERMITTENT", error_rate=0.5)
    outcomes = set()
    for i in range(60):
        try:
            outcomes.add(sim.call("pharmacy", "check_prescription", PAY, 2, f"i{i}").status_code)
        except PartnerTimeout:
            outcomes.add("timeout")
    assert 200 in outcomes and len(outcomes) > 2


def test_recovery_restores_normal(sim):
    sim.set_mode("insurance", "UNAVAILABLE")
    assert sim.call("insurance", "verify_eligibility", PAY, 5, "a").status_code == 503
    sim.recover("insurance")
    assert sim.call("insurance", "verify_eligibility", PAY, 5, "b").status_code == 200


def test_simulation_duration_expires(sim, clock):
    sim.set_mode("laboratory", "UNAVAILABLE", duration_seconds=10)
    assert sim.call("laboratory", "order_test", PAY, 5, "a").status_code == 503
    clock.sleep(10.5)
    assert sim.call("laboratory", "order_test", PAY, 5, "b").status_code == 200


def test_validation_error_is_permanent_400(sim):
    assert sim.call("laboratory", "order_test", {}, 5, "x").status_code == 400


def test_same_request_key_gives_same_partner_behaviour(cfg):
    cfg["partners"]["pharmacy"]["failure_rate"] = 0.5
    outs = []
    for _ in range(2):
        s = PartnerSimulator(cfg, VirtualClock(), seed=5)
        outs.append([s.call("pharmacy", "check_prescription", PAY, 5, f"k{i}").status_code for i in range(30)])
    assert outs[0] == outs[1]
