"""Flask application factory for the Hospital Dependency Resilience Platform.

Synthetic data and simulated partner services only. Not intended for production clinical use.
"""
import json
import logging
import os
import secrets
import sys
import threading

import markdown as md
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.auth.auth import (ROLE_LABELS, current_user, has_permission, login_required, pages_for,
                           permission_required)
from src.core.hospital_service import DEFAULT_OPERATION, HospitalCoreService
from src.database.db import Database
from src.monitoring.metrics import compute_metrics
from src.partners.partner_simulator import MODES, PARTNERS
from src.utils import validation_survey as survey
from src.utils.clock import RealClock
from src.utils.config_manager import ConfigError, ConfigManager

ROOT = os.path.abspath(os.path.dirname(__file__))
DISCLAIMER = ("This system uses synthetic data and simulated partner services. "
              "It is not intended for production clinical use.")
REPORT_FILES = {
    "README": "README.md",
    "project_report": "docs/project_report.md",
    "technical_documentation": "docs/technical_documentation.md",
    "failure_mode_analysis": "docs/failure_mode_analysis.md",
    "experiment_report": "docs/experiment_report.md",
    "user_feedback_summary": "docs/user_feedback_summary.md",
    "presentation_outline": "presentation/presentation_outline.md",
}
SIM_MODES = MODES + ["RECOVERY"]


def create_app(config_path=None, db_path=None, clock=None, seed=None, persist_config=True,
               start_monitor=False, results_dir=None):
    config_path = config_path or os.path.join(ROOT, "config", "config.yaml")
    db_path = db_path or os.path.join(ROOT, "data", "hospital_resilience.db")
    results_dir = results_dir or os.path.join(ROOT, "data", "results")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    key = os.environ.get("SECRET_KEY")
    if not key:
        keyfile = os.path.join(os.path.dirname(db_path) or ".", ".secret_key")
        os.makedirs(os.path.dirname(keyfile) or ".", exist_ok=True)
        if os.path.exists(keyfile):
            key = open(keyfile).read().strip()
        else:
            key = secrets.token_hex(32)
            with open(keyfile, "w") as fh:
                fh.write(key)
    app.secret_key = key

    cm = ConfigManager(config_path, persist=persist_config)
    db = Database(db_path)
    db.initialize(cm.get())
    hospital = HospitalCoreService(cm, db=db, clock=clock or RealClock(),
                                   seed=seed if seed is not None else secrets.randbelow(10**6))
    app.extensions["hospital"] = hospital
    app.extensions["db"] = db
    app.extensions["config_manager"] = cm
    exp_lock = threading.Lock()

    if start_monitor:
        from src.monitoring.health_monitor import HealthMonitor
        mon = HealthMonitor(hospital, cm.get()["monitoring"]["probe_interval_seconds"])
        mon.start()
        app.extensions["monitor"] = mon

    log = logging.getLogger("HospitalApp")

    def bad(msg, code=400, **extra):
        return jsonify({"error": msg, **extra}), code

    def body():
        return request.get_json(silent=True) or {}

    # ================================================================ pages & auth
    @app.route("/")
    def index():
        return redirect(url_for("app_page") if current_user() else url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html", disclaimer=DISCLAIMER, error=None)
        data = request.get_json(silent=True) or request.form
        user = db.verify_user((data.get("username") or "").strip(), data.get("password") or "")
        if not user:
            if request.is_json:
                return bad("Invalid username or password", 401)
            return render_template("login.html", disclaimer=DISCLAIMER, error="Invalid username or password"), 401
        session.clear()
        session["user"] = user
        if request.is_json:
            return jsonify({"success": True, "user": user, "pages": pages_for(user)})
        return redirect(url_for("app_page"))

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        if request.is_json or request.path.startswith("/api/"):
            return jsonify({"success": True})
        return redirect(url_for("login"))

    @app.route("/app")
    @login_required
    def app_page():
        user = current_user()
        return render_template("app.html", user=user, role_label=ROLE_LABELS.get(user["role"], user["role"]),
                               pages=pages_for(user), disclaimer=DISCLAIMER,
                               perms=sorted(p for p in ("config_write", "simulate", "experiments_run", "baseline_mode",
                                                        "validation_view") if has_permission(user, p)))

    @app.route("/api/me")
    @login_required
    def me():
        user = current_user()
        return jsonify({"user": user, "role_label": ROLE_LABELS.get(user["role"]), "pages": pages_for(user)})

    @app.route("/outputs/figures/<path:filename>")
    @permission_required("experiments_view", "reports")
    def figures(filename):
        return send_from_directory(os.path.join(ROOT, "outputs", "figures"), filename)

    # ====================================================================== health
    @app.route("/api/health")
    def api_health():
        try:
            db.query_one("SELECT 1 AS ok")
            db_ok = True
        except Exception:
            db_ok = False
        return jsonify({"status": "ok" if db_ok else "degraded", "database": db_ok,
                        "service": "Hospital Dependency Resilience Platform", "time": hospital.clock.now_iso(),
                        "disclaimer": DISCLAIMER})

    # ===================================================================== partners
    def _check_partner(name):
        name = name.lower()
        if name not in PARTNERS:
            return None
        return name

    def _reduced(p):
        """Clinical-staff view: plain-language status only, no tuning internals."""
        return {"partner": p["partner"], "display_name": p["display_name"], "status": p["status"],
                "color": p["color"], "message": p["message"], "circuit_state": p["circuit"]["state"]}

    @app.route("/api/partners")
    @permission_required("partner_status")
    def api_partners():
        ov = hospital.partners_overview()
        if has_permission(current_user(), "partner_health"):
            return jsonify({"partners": ov})
        return jsonify({"partners": {k: _reduced(v) for k, v in ov.items()}})

    @app.route("/api/partners/<partner>/health")
    @permission_required("partner_status")
    def api_partner_health(partner):
        p = _check_partner(partner)
        if not p:
            return bad("Unknown partner", 404)
        user = current_user()
        probe = None
        if request.args.get("probe") in ("1", "true"):
            if not has_permission(user, "partner_health"):
                return bad("Your role is not permitted to run health probes", 403)
            probe = hospital.probe(p)
        ov = hospital.partners_overview()[p]
        out = ov if has_permission(user, "partner_health") else _reduced(ov)
        if probe:
            out = {**out, "probe": {k: probe[k] for k in ("success", "latency_ms", "error_type", "status_code")}}
        return jsonify(out)

    @app.route("/api/partners/<partner>/simulate", methods=["POST"])
    @permission_required("simulate")
    def api_simulate(partner):
        p = _check_partner(partner)
        if not p:
            return bad("Unknown partner", 404)
        d = body()
        mode = str(d.get("mode", "")).upper()
        if mode not in SIM_MODES:
            return bad(f"mode must be one of {SIM_MODES}")
        try:
            latency = d.get("latency_ms")
            latency = float(latency) if latency not in (None, "") else None
            err = d.get("error_rate")
            if err not in (None, ""):
                from src.utils.config_manager import parse_rate
                err = parse_rate(err)
                if not 0 <= err <= 1:
                    raise ValueError
            else:
                err = None
            dur = d.get("duration_seconds")
            dur = float(dur) if dur not in (None, "", 0, "0") else None
            if (latency is not None and not 0 <= latency <= 120000) or (dur is not None and dur <= 0):
                raise ValueError
        except (TypeError, ValueError):
            return bad("latency_ms must be 0-120000, error_rate 0-1 (or 0%-100%), duration_seconds > 0")
        state = hospital.simulate(p, mode, latency, err, dur)
        log.info("Simulation %s -> %s", p, mode)
        return jsonify({"success": True, "partner": p, "state": state})

    @app.route("/api/partners/<partner>/recover", methods=["POST"])
    @permission_required("simulate")
    def api_recover(partner):
        p = _check_partner(partner)
        if not p:
            return bad("Unknown partner", 404)
        state = hospital.recover(p)
        return jsonify({"success": True, "partner": p, "state": state,
                        "circuit": hospital.resilience.breakers[p].info(),
                        "note": "Partner restored. The circuit breaker will move OPEN -> HALF_OPEN -> CLOSED on its own as test calls succeed."})

    @app.route("/api/partners/<partner>/test-call", methods=["POST"])
    @permission_required("simulate")
    def api_test_call(partner):
        """Manager-side traffic generator using a synthetic test patient (no patient data touched)."""
        p = _check_partner(partner)
        if not p:
            return bad("Unknown partner", 404)
        d = body()
        count = max(1, min(int(d.get("count", 1) or 1), 20))
        mode = d.get("mode", "resilient")
        if mode not in ("resilient", "baseline"):
            return bad("mode must be resilient or baseline")
        results = [hospital.execute_partner(p, DEFAULT_OPERATION[p], {"patient_id": "P-TEST"}, mode=mode)
                   for _ in range(count)]
        return jsonify({"results": [_public_result(r) for r in results]})

    @app.route("/api/dependencies")
    @permission_required("dependency_map")
    def api_dependencies():
        return jsonify(hospital.dependency_map())

    # ============================================================ metrics / logs
    @app.route("/api/metrics")
    @permission_required("metrics")
    def api_metrics():
        mode = request.args.get("mode")
        calls = hospital.recorder.calls()
        if mode in ("baseline", "resilient"):
            calls = [c for c in calls if c["mode"] == mode]
        ids = {c["request_id"] for c in calls}
        attempts = [a for a in hospital.recorder.attempts() if a["request_id"] in ids]
        events = hospital.recorder.circuit_events()
        out = compute_metrics(calls, attempts, events)
        out["per_partner"] = {p: compute_metrics([c for c in calls if c["partner"] == p],
                                                 [a for a in attempts if a["partner"] == p],
                                                 [e for e in events if e["partner"] == p]) for p in PARTNERS}
        return jsonify(out)

    @app.route("/api/logs")
    @permission_required("logs")
    def api_logs():
        limit = max(1, min(int(request.args.get("limit", 100)), 1000))
        partner = request.args.get("partner")
        rid = request.args.get("request_id")
        calls = hospital.recorder.calls(partner=partner, limit=limit, include_probes=True)
        calls = list(reversed(calls))
        out = {"calls": calls,
               "circuit_events": list(reversed(hospital.recorder.circuit_events()[-50:])),
               "failure_events": db.query("SELECT * FROM failure_events ORDER BY id DESC LIMIT 50")}
        if rid:
            out["attempts"] = hospital.recorder.attempts(request_id=rid)
        else:
            out["attempts"] = hospital.recorder.attempts()[-200:]
        return jsonify(out)

    @app.route("/api/status")
    @permission_required("dashboard")
    def api_status():
        calls = hospital.recorder.calls()
        metrics = compute_metrics(calls, hospital.recorder.attempts(), hospital.recorder.circuit_events())
        return jsonify({"partners": hospital.partners_overview(), "metrics": metrics,
                        "recent_calls": list(reversed(calls[-15:])),
                        "circuit_events": list(reversed(hospital.recorder.circuit_events()[-10:])),
                        "dependencies": hospital.dependency_map(), "pending_actions":
                        db.query_one("SELECT COUNT(*) AS n FROM pending_actions WHERE status='PENDING'")["n"],
                        "time": hospital.clock.now_iso()})

    # ===================================================================== config
    @app.route("/api/config", methods=["GET", "POST"])
    @permission_required("config_read", "config_write")
    def api_config():
        user = current_user()
        if request.method == "GET":
            if not has_permission(user, "config_read"):
                return bad("Your role is not permitted to view configuration", 403)
            return jsonify(cm.get())
        if not has_permission(user, "config_write"):
            return bad("Your role is not permitted to change configuration", 403)
        try:
            new = cm.update(body())
        except ConfigError as e:
            return bad("Invalid configuration", 400, details=e.errors)
        hospital.reload_config()
        log.info("Configuration updated by %s", user["username"])
        return jsonify({"success": True, "config": new, "version": cm.version})

    # ================================================================== patients
    def _public_result(r):
        keys = ("request_id", "partner", "operation", "mode", "timestamp", "status", "success", "core_ok",
                "fallback_used", "message", "retry_count", "attempt_count", "attempts", "circuit_state",
                "latency_ms", "error_type", "data", "reason")
        return {k: r.get(k) for k in keys}

    @app.route("/api/patients", methods=["GET", "POST"])
    @permission_required("patients")
    def api_patients():
        if request.method == "GET":
            return jsonify({"patients": db.list_patients()})
        d = body()
        name = str(d.get("patient_name", "")).strip()
        try:
            age = int(d.get("age"))
        except (TypeError, ValueError):
            return bad("age must be a whole number")
        if not name or not 0 <= age <= 120:
            return bad("patient_name is required and age must be 0-120")
        if not name.lower().endswith("(synthetic)"):
            name += " (synthetic)"
        pat = db.add_patient(name, age, d.get("gender", "F"), d.get("department", "General Medicine"),
                             hospital.clock.now_iso()[:10])
        return jsonify({"patient": pat}), 201

    @app.route("/api/patients/<patient_id>")
    @permission_required("patients")
    def api_patient(patient_id):
        pat = db.get_patient(patient_id)
        if not pat:
            return bad("Patient not found", 404)
        pend = db.query("SELECT partner,operation,status,timestamp FROM pending_actions WHERE patient_id=? ORDER BY id DESC",
                        (patient_id,))
        return jsonify({"patient": pat, "appointments": db.list_appointments(patient_id), "pending_actions": pend})

    @app.route("/api/appointments", methods=["POST"])
    @permission_required("appointments")
    def api_appointments():
        d = body()
        if not db.get_patient(d.get("patient_id", "")):
            return bad("Patient not found", 404)
        for f in ("doctor", "appointment_date"):
            if not str(d.get(f, "")).strip():
                return bad(f"{f} is required")
        appt = db.add_appointment(d["patient_id"], d["doctor"], d["appointment_date"], d.get("appointment_type", "Consultation"))
        return jsonify({"appointment": appt}), 201

    def _partner_op(partner):
        d = body()
        pid = d.get("patient_id")
        if not pid or not db.get_patient(pid):
            return bad("Unknown or missing patient_id", 404 if pid else 400)
        mode = d.get("mode", "resilient")
        if mode not in ("resilient", "baseline"):
            return bad("mode must be resilient or baseline")
        if mode == "baseline" and not has_permission(current_user(), "baseline_mode"):
            return bad("Clinical staff always use the protected (resilient) mode", 403)
        payload = {"patient_id": pid}
        for k in ("test_type", "medication", "provider", "slot"):
            if d.get(k):
                payload[k] = str(d[k])[:80]
        res = hospital.execute_partner(partner, DEFAULT_OPERATION[partner], payload, mode=mode)
        return jsonify(_public_result(res))

    @app.route("/api/laboratory/request", methods=["POST"])
    @permission_required("partner_ops")
    def api_lab():
        return _partner_op("laboratory")

    @app.route("/api/pharmacy/check", methods=["POST"])
    @permission_required("partner_ops")
    def api_pharmacy():
        return _partner_op("pharmacy")

    @app.route("/api/insurance/verify", methods=["POST"])
    @permission_required("partner_ops")
    def api_insurance():
        return _partner_op("insurance")

    @app.route("/api/telemedicine/book", methods=["POST"])
    @permission_required("partner_ops")
    def api_telemedicine():
        return _partner_op("telemedicine")

    @app.route("/api/patients/<patient_id>/visit", methods=["POST"])
    @permission_required("partner_ops")
    def api_visit(patient_id):
        if not db.get_patient(patient_id):
            return bad("Patient not found", 404)
        mode = body().get("mode", "resilient")
        if mode == "baseline" and not has_permission(current_user(), "baseline_mode"):
            return bad("Clinical staff always use the protected (resilient) mode", 403)
        v = hospital.run_patient_visit(f"VISIT-{hospital.new_request_id()[4:]}", patient_id, mode)
        v.pop("t_start", None); v.pop("t_end", None)
        return jsonify(v)

    # ================================================================ experiments
    def _load_results():
        out = {"available": False}
        summ = os.path.join(results_dir, "experiment_summary.json")
        if os.path.exists(summ):
            with open(summ, encoding="utf-8") as fh:
                out["summary"] = json.load(fh)
            out["available"] = True
        comp = os.path.join(results_dir, "comparison_results.csv")
        if os.path.exists(comp):
            import pandas as pd
            out["comparison"] = json.loads(pd.read_csv(comp).to_json(orient="records"))
        figs = os.path.join(ROOT, "outputs", "figures")
        out["figures"] = sorted(f for f in os.listdir(figs) if f.endswith(".png")) if os.path.isdir(figs) else []
        out["runs"] = db.query("SELECT * FROM experiment_runs ORDER BY id DESC LIMIT 40")
        return out

    @app.route("/api/experiments")
    @permission_required("experiments_view")
    def api_experiments():
        return jsonify(_load_results())

    @app.route("/api/experiments/run", methods=["POST"])
    @permission_required("experiments_run")
    def api_experiments_run():
        if not exp_lock.acquire(blocking=False):
            return bad("An experiment run is already in progress", 409)
        try:
            from experiments.runner import run_suite
            run_suite(cm, db=db, results_dir=results_dir, figures_dir=os.path.join(ROOT, "outputs", "figures"),
                      reports_dir=os.path.join(ROOT, "docs"), verbose=False)
        except Exception as ex:  # pragma: no cover
            log.exception("experiment run failed")
            return bad(f"Experiment run failed: {ex}", 500)
        finally:
            exp_lock.release()
        return jsonify({"success": True, **_load_results()})

    # ================================================================ validation
    @app.route("/api/validation/questions")
    @permission_required("validation_submit")
    def api_val_questions():
        return jsonify({"questions": survey.QUESTIONS, "disclaimer": survey.DISCLAIMER})

    @app.route("/api/validation", methods=["GET", "POST"])
    @permission_required("validation_submit")
    def api_validation():
        user = current_user()
        if request.method == "POST":
            try:
                n = survey.save_submission(db, user["role"], body().get("answers", {}), hospital.clock.now_iso())
            except (ValueError, TypeError) as e:
                return bad(str(e))
            return jsonify({"success": True, "stored_answers": n, "disclaimer": survey.DISCLAIMER}), 201
        if not has_permission(user, "validation_view"):
            return bad("Your role is not permitted to view collected feedback", 403)
        return jsonify({"disclaimer": survey.DISCLAIMER, "summary": survey.summarize(db),
                        "rows": db.query("SELECT * FROM user_feedback ORDER BY id DESC LIMIT 200")})

    @app.route("/api/validation/summary", methods=["POST"])
    @permission_required("validation_view")
    def api_val_summary():
        text = survey.render_summary_md(db)
        path = os.path.join(ROOT, "docs", "user_feedback_summary.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return jsonify({"success": True, "path": "docs/user_feedback_summary.md"})

    # ================================================================== reports
    @app.route("/api/reports")
    @permission_required("reports")
    def api_reports():
        return jsonify({"reports": [{"key": k, "path": v, "exists": os.path.exists(os.path.join(ROOT, v))}
                                    for k, v in REPORT_FILES.items()]})

    @app.route("/api/reports/<key>")
    @permission_required("reports")
    def api_report(key):
        rel = REPORT_FILES.get(key)
        path = os.path.join(ROOT, rel) if rel else None
        if not path or not os.path.exists(path):
            return bad("Report not found", 404)
        with open(path, encoding="utf-8") as fh:
            html = md.markdown(fh.read(), extensions=["tables", "fenced_code"])
        return jsonify({"key": key, "html": html})

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app().run(host="127.0.0.1", port=5000, threaded=True)
