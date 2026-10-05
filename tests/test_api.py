import yaml

from tests.conftest import login


def test_health_is_public(app_env):
    app, _, _ = app_env
    r = app.test_client().get("/api/health")
    assert r.status_code == 200 and r.get_json()["database"] is True
    assert "synthetic data" in r.get_json()["disclaimer"]


def test_login_failure_and_unauthenticated_access(app_env):
    app, _, _ = app_env
    c = app.test_client()
    assert c.post("/login", json={"username": "manager", "password": "nope"}).status_code == 401
    assert c.get("/api/partners").status_code == 401
    assert c.get("/app").status_code == 302


def test_roles_and_pages(app_env):
    app, _, _ = app_env
    m = login(app, "manager", "manager123").get("/api/me").get_json()
    c = login(app, "clinician", "clinician123").get("/api/me").get_json()
    assert m["user"]["role"] == "operations_manager" and c["user"]["role"] == "clinical_staff"
    mp = {p["key"] for p in m["pages"]}
    cp = {p["key"] for p in c["pages"]}
    assert {"dashboard", "depmap", "simulation", "config", "experiments", "logs", "reports"} <= mp
    assert "patients" in cp and not ({"config", "simulation", "experiments", "logs", "dashboard"} & cp)


def test_clinician_cannot_configure_simulate_run_experiments_or_read_logs(app_env):
    app, _, _ = app_env
    c = login(app, "clinician", "clinician123")
    assert c.get("/api/config").status_code == 403
    assert c.post("/api/config", json={"resilience": {"retry": {"max_attempts": 1}}}).status_code == 403
    assert c.post("/api/partners/insurance/simulate", json={"mode": "UNAVAILABLE"}).status_code == 403
    assert c.post("/api/partners/insurance/recover").status_code == 403
    assert c.post("/api/experiments/run").status_code == 403
    for path in ("/api/logs", "/api/metrics", "/api/dependencies", "/api/status", "/api/experiments"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/laboratory/request", json={"patient_id": "P-1001", "mode": "baseline"}).status_code == 403


def test_manager_cannot_access_patient_data(app_env):
    app, _, _ = app_env
    m = login(app, "manager", "manager123")
    assert m.get("/api/patients").status_code == 403
    assert m.post("/api/insurance/verify", json={"patient_id": "P-1001"}).status_code == 403


def test_clinician_partner_status_is_reduced(app_env):
    app, _, _ = app_env
    c = login(app, "clinician", "clinician123")
    d = c.get("/api/partners").get_json()["partners"]["insurance"]
    assert "status" in d and "message" in d and "simulation" not in d and "circuit" not in d
    assert c.get("/api/partners/insurance/health?probe=1").status_code == 403


def test_patients_and_appointments_api(app_env):
    app, _, _ = app_env
    c = login(app, "clinician", "clinician123")
    pts = c.get("/api/patients").get_json()["patients"]
    assert len(pts) >= 20 and all("(synthetic)" in p["patient_name"] for p in pts)
    one = c.get(f"/api/patients/{pts[0]['patient_id']}").get_json()
    assert one["patient"]["patient_id"] == pts[0]["patient_id"] and one["appointments"]
    assert c.get("/api/patients/NOPE").status_code == 404
    r = c.post("/api/appointments", json={"patient_id": "P-1001", "doctor": "Dr. X", "appointment_date": "2026-12-01 09:00"})
    assert r.status_code == 201 and r.get_json()["appointment"]["status"] == "SCHEDULED"
    assert c.post("/api/appointments", json={"patient_id": "NOPE", "doctor": "x", "appointment_date": "y"}).status_code == 404
    reg = c.post("/api/patients", json={"patient_name": "Test Person", "age": 33})
    assert reg.status_code == 201 and "(synthetic)" in reg.get_json()["patient"]["patient_name"]
    assert c.post("/api/patients", json={"patient_name": "", "age": 33}).status_code == 400


def test_four_partner_endpoints_return_dynamic_data(app_env):
    app, _, _ = app_env
    c = login(app, "clinician", "clinician123")
    for path in ("/api/laboratory/request", "/api/pharmacy/check", "/api/insurance/verify", "/api/telemedicine/book"):
        r = c.post(path, json={"patient_id": "P-1001"})
        j = r.get_json()
        assert r.status_code == 200 and j["status"] == "SUCCESS" and j["success"] and j["latency_ms"] > 0
    assert c.post("/api/insurance/verify", json={"patient_id": "UNKNOWN"}).status_code == 404
    assert c.post("/api/insurance/verify", json={}).status_code == 400


def test_config_api_validates_and_changes_actual_behaviour(app_env):
    app, clock, cpath = app_env
    m = login(app, "manager", "manager123")
    bad = m.post("/api/config", json={"resilience": {"retry": {"max_attempts": 9}}})
    assert bad.status_code == 400 and bad.get_json()["details"]
    assert m.post("/api/config", json={"partners": {"insurance": {"failure_rate": 1.5}}}).status_code == 400
    ok = m.post("/api/config", json={"partners": {"insurance": {"failure_rate": "100%", "latency_ms": 800}},
                                     "resilience": {"retry": {"max_attempts": 1}}})
    assert ok.status_code == 200
    assert yaml.safe_load(cpath.read_text())["partners"]["insurance"]["failure_rate"] == 1.0   # persisted
    cl = login(app, "clinician", "clinician123")
    r = cl.post("/api/insurance/verify", json={"patient_id": "P-1001"}).get_json()
    assert r["fallback_used"] and r["retry_count"] == 1          # new rate (100%) and new retry limit really applied
    assert m.get("/api/config").get_json()["resilience"]["retry"]["max_attempts"] == 1


def test_simulate_validation_and_unknown_partner(app_env):
    app, _, _ = app_env
    m = login(app, "manager", "manager123")
    assert m.post("/api/partners/nope/simulate", json={"mode": "NORMAL"}).status_code == 404
    assert m.post("/api/partners/insurance/simulate", json={"mode": "EXPLODE"}).status_code == 400
    assert m.post("/api/partners/insurance/simulate", json={"mode": "INTERMITTENT", "error_rate": 3}).status_code == 400


def test_metrics_logs_and_failure_events_are_dynamic(app_env):
    app, _, _ = app_env
    m, c = login(app, "manager", "manager123"), login(app, "clinician", "clinician123")
    assert m.get("/api/metrics").get_json()["total_requests"] == 0
    m.post("/api/partners/laboratory/simulate", json={"mode": "UNAVAILABLE"})
    c.post("/api/laboratory/request", json={"patient_id": "P-1001"})
    met = m.get("/api/metrics").get_json()
    assert met["total_requests"] == 1 and met["fallback_count"] == 1 and met["retry_count"] == 2 and met["circuit_open_count"] == 1
    logs = m.get("/api/logs").get_json()
    row = logs["calls"][0]
    for k in ("timestamp", "request_id", "partner", "operation", "latency_ms", "status", "error_type", "retry_count",
              "circuit_state", "fallback_used"):
        assert k in row
    assert len(logs["attempts"]) == 3 and logs["circuit_events"][0]["new_state"] == "OPEN"
    assert logs["failure_events"][0]["failure_type"] == "UNAVAILABLE" and logs["failure_events"][0]["resolved"] == 0
    m.post("/api/partners/laboratory/recover")


def test_validation_questionnaire_stores_in_sqlite_and_summary(app_env, tmp_path):
    app, _, _ = app_env
    c, m = login(app, "clinician", "clinician123"), login(app, "manager", "manager123")
    qs = c.get("/api/validation/questions").get_json()
    assert len(qs["questions"]) == 7 and "Prototype/simulated" in qs["disclaimer"]
    r = c.post("/api/validation", json={"answers": {"q1": 4, "q2": 5, "q7": "Show retry counts"}})
    assert r.status_code == 201
    assert c.post("/api/validation", json={"answers": {"q1": 9}}).status_code == 400
    assert c.get("/api/validation").status_code == 403           # clinicians cannot read others' feedback
    s = m.get("/api/validation").get_json()["summary"]
    assert s["roles"]["clinical_staff"]["questions"]["Is dependency status understandable?"]["mean"] == 4
    from src.utils.validation_survey import render_summary_md
    md = render_summary_md(app.extensions["db"])
    assert "Prototype/simulated user validation" in md and "Show retry counts" in md
