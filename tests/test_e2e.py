"""End-to-end: the full failure -> retry -> circuit open -> fallback -> recovery -> HALF_OPEN -> CLOSED story."""
from tests.conftest import login


def test_full_resilience_lifecycle(app_env):
    app, clock, _ = app_env
    db = app.extensions["db"]
    # 1-2. login + dashboard
    mgr = login(app, "manager", "manager123")
    clin = login(app, "clinician", "clinician123")
    assert mgr.get("/app").status_code == 200
    assert mgr.get("/api/status").status_code == 200
    # 3. Insurance healthy
    assert mgr.post("/api/partners/insurance/test-call", json={"count": 2}).get_json()["results"][0]["status"] == "SUCCESS"
    assert mgr.get("/api/partners/insurance/health").get_json()["status"] == "HEALTHY"
    dep = {n["id"]: n for n in mgr.get("/api/dependencies").get_json()["nodes"]}
    assert dep["insurance"]["color"] == "green"
    # 4. trigger Insurance failure
    sim = mgr.post("/api/partners/insurance/simulate", json={"mode": "UNAVAILABLE"}).get_json()
    assert sim["state"]["mode"] == "UNAVAILABLE"
    # 5-7. clinician makes insurance requests -> failures, retries, circuit opens
    r1 = clin.post("/api/insurance/verify", json={"patient_id": "P-1001"}).get_json()
    assert r1["retry_count"] == 2 and r1["circuit_state"] == "OPEN"
    assert [a["result"] for a in r1["attempts"]] == ["HTTP_503"] * 3
    # 9. truthful fallback
    assert r1["fallback_used"] and r1["success"] is False and r1["status"] == "TEMPORARILY_UNAVAILABLE"
    assert "recorded for later verification" in r1["message"] and r1["data"]["eligibility_confirmed"] is False
    assert db.query_one("SELECT COUNT(*) n FROM pending_actions WHERE status='PENDING'")["n"] == 1   # message is literally true
    # fail-fast
    r2 = clin.post("/api/insurance/verify", json={"patient_id": "P-1002"}).get_json()
    assert r2["status"] == "CIRCUIT_OPEN" and r2["latency_ms"] == 0 and r2["attempts"] == []
    dep = {n["id"]: n for n in mgr.get("/api/dependencies").get_json()["nodes"]}
    assert dep["insurance"]["status"] == "CIRCUIT_OPEN" and dep["insurance"]["color"] == "gray"
    # 10. core patient workflow still works with Insurance down
    assert clin.get("/api/patients/P-1001").status_code == 200
    visit = clin.post("/api/patients/P-1001/visit", json={}).get_json()
    assert visit["core_ok"] is True and visit["status"] == "COMPLETED_DEGRADED" and visit["degraded_steps"] == ["insurance"]
    ins_step = [s for s in visit["steps"] if s["step"] == "insurance"][0]
    assert ins_step["status"] == "CIRCUIT_OPEN" and ins_step["status"] != "SUCCESS"
    assert [s["status"] for s in visit["steps"] if s["step"] in ("laboratory", "pharmacy", "telemedicine")] == ["SUCCESS"] * 3
    # baseline comparison (manager): same outage propagates to the core
    base = mgr.post("/api/patients/P-1001/visit", json={"mode": "baseline"})
    assert base.status_code == 403   # manager has no patient-data access; use test-call for baseline
    bcall = mgr.post("/api/partners/insurance/test-call", json={"mode": "baseline"}).get_json()["results"][0]
    assert bcall["status"] == "ERROR" and bcall["core_ok"] is False
    # 11. recover Insurance
    rec = mgr.post("/api/partners/insurance/recover").get_json()
    assert rec["state"]["mode"] == "NORMAL" and rec["circuit"]["state"] == "OPEN"   # breaker still OPEN until it tests
    assert clin.post("/api/insurance/verify", json={"patient_id": "P-1003"}).get_json()["status"] == "CIRCUIT_OPEN"
    # 12-14. recovery timeout elapses -> HALF_OPEN trial -> success -> CLOSED
    clock.sleep(10.5)
    ok = clin.post("/api/insurance/verify", json={"patient_id": "P-1004"}).get_json()
    assert ok["status"] == "RECOVERED" and ok["success"] and ok["circuit_state"] == "CLOSED"
    transitions = [(e["old_state"], e["new_state"]) for e in mgr.get("/api/logs").get_json()["circuit_events"]]
    assert ("CLOSED", "OPEN") in transitions and ("OPEN", "HALF_OPEN") in transitions and ("HALF_OPEN", "CLOSED") in transitions
    # deferred request was replayed automatically after recovery
    assert db.query_one("SELECT COUNT(*) n FROM pending_actions WHERE status='SYNCED'")["n"] >= 1
    # failure event resolved with a recovery time
    fe = mgr.get("/api/logs").get_json()["failure_events"][0]
    assert fe["resolved"] == 1 and fe["recovery_time"] > 0
    # 15. normal operation resumes
    again = clin.post("/api/insurance/verify", json={"patient_id": "P-1005"}).get_json()
    assert again["status"] == "SUCCESS" and again["retry_count"] == 0
    assert clin.post("/api/patients/P-1001/visit", json={}).get_json()["status"] == "COMPLETED"
    assert mgr.get("/api/partners/insurance/health").get_json()["circuit"]["state"] == "CLOSED"
    m = mgr.get("/api/metrics").get_json()
    assert m["circuit_open_count"] == 1 and m["fallback_count"] >= 3 and m["retry_count"] >= 2
