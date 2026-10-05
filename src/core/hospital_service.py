"""Hospital core service: orchestrates local workflow steps and guarded partner calls."""
import threading
import uuid

from src.baseline.baseline_client import BaselineClient
from src.monitoring.health import COLORS, compute_health
from src.monitoring.recorder import DBRecorder, MemoryRecorder
from src.partners.partner_simulator import BUILDERS, PARTNERS, PartnerSimulator
from src.resilience.resilience_manager import ResilienceManager
from src.utils.clock import RealClock

DEFAULT_OPERATION = {"laboratory": "order_test", "pharmacy": "check_prescription",
                     "insurance": "verify_eligibility", "telemedicine": "book_consult"}
SEVERITY = {"UNAVAILABLE": "critical", "CONTINUOUS_FAILURE": "critical", "TIMEOUT": "high",
            "HIGH_LATENCY": "medium", "INTERMITTENT": "medium"}
LOCAL_STEP_MS = 5.0   # registration / appointment / consultation are local hospital operations


class HospitalCoreService:
    """Executes partner operations in 'resilient' or 'baseline' mode.

    db=None  -> pure in-memory operation (used by the experiment runner).
    """

    def __init__(self, config_manager, db=None, recorder=None, clock=None, seed=0,
                 enable_pending_sync=True, source="live"):
        self.cm = config_manager
        self.config = config_manager.get()
        self.db = db
        self.clock = clock or RealClock()
        self.recorder = recorder or (DBRecorder(db) if db else MemoryRecorder())
        self.source = source
        self.enable_pending_sync = enable_pending_sync and db is not None
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._counter = 0
        self._open_event = {}      # partner -> failure_events row id
        self._awaiting_close = {}  # partner -> (event id, recovered_at) waiting for circuit CLOSED
        self.simulator = PartnerSimulator(self.config, self.clock, seed=seed, on_expire=self._on_sim_expire)
        self.resilience = ResilienceManager(self.config, self.clock, self.simulator.call, self._on_transition)
        self.baseline = BaselineClient(self.config, self.clock, self.simulator.call)
        if db:
            db.seed_partners(self.config)

    # ------------------------------------------------------------ configuration
    def reload_config(self):
        self.config = self.cm.get()
        self.simulator.apply_config(self.config)
        self.resilience.reconfigure(self.config)
        self.baseline = BaselineClient(self.config, self.clock, self.simulator.call)
        if self.db:
            for p, cfg in self.config["partners"].items():
                self.db.update_partner_row(p, latency_ms=cfg["latency_ms"], error_rate=cfg["failure_rate"])

    # ------------------------------------------------------------------ requests
    def new_request_id(self):
        return f"REQ-{uuid.uuid4().hex[:8].upper()}"

    def execute_partner(self, partner, operation=None, payload=None, mode="resilient",
                        request_id=None, source=None, _sync=False):
        partner = partner.lower()
        if partner not in BUILDERS:
            raise ValueError(f"Unknown partner: {partner}")
        operation = operation or DEFAULT_OPERATION[partner]
        payload = dict(payload or {})
        request_id = request_id or self.new_request_id()
        source = source or self.source
        t0 = self.clock.time()
        if mode == "baseline":
            result = self.baseline.execute(partner, operation, payload, request_id)
        else:
            result = self.resilience.execute(partner, operation, payload, request_id)
        result["timestamp"] = self.clock.now_iso()
        if result["queue_for_sync"] and self.db and self.enable_pending_sync and payload.get("patient_id"):
            pid = self.db.execute(
                "INSERT INTO pending_actions(request_id,timestamp,partner,operation,patient_id,status) VALUES (?,?,?,?,?,'PENDING')",
                (request_id, result["timestamp"], partner, operation, payload["patient_id"]))
            result["data"] = {**result["data"], "pending_action_id": pid}
        elif result["queue_for_sync"]:
            result["data"] = {**result["data"], "pending_action_id": None}
        self.recorder.record_call(result, source, t_start=t0, t_end=self.clock.time())
        self._refresh_partner_row(partner, result)
        if result["success"] and not _sync and self.enable_pending_sync:
            if self.clock.virtual:
                self.process_pending(partner)          # deterministic in tests / simulations
            else:                                      # live app: never delay the user's request
                threading.Thread(target=self._safe_sync, args=(partner,), daemon=True).start()
        return result

    def _safe_sync(self, partner):
        with self._sync_lock:
            try:
                self.process_pending(partner)
            except Exception:
                pass

    def process_pending(self, partner, limit=3):
        """Replay queued requests (laboratory / insurance) once the partner answers again."""
        rows = self.db.query("SELECT * FROM pending_actions WHERE partner=? AND status='PENDING' ORDER BY id LIMIT ?",
                             (partner, limit))
        done = 0
        for row in rows:
            r = self.execute_partner(partner, row["operation"], {"patient_id": row["patient_id"]},
                                     mode="resilient", request_id=f"SYNC-{row['id']}", source="sync", _sync=True)
            if not r["success"]:
                break
            self.db.execute("UPDATE pending_actions SET status='SYNCED', synced_at=? WHERE id=?",
                            (self.clock.now_iso(), row["id"]))
            done += 1
        return done

    # ----------------------------------------------------------- patient workflow
    def run_patient_visit(self, visit_id, patient_id, mode="resilient", source=None):
        """registration -> appointment -> consultation -> laboratory -> pharmacy -> insurance -> telemedicine.

        Partner steps are synchronous parts of the visit. If a partner error reaches the core
        (baseline) the visit fails at that step (cascading failure); otherwise it completes,
        possibly DEGRADED.
        """
        start = self.clock.time()
        steps = []
        for local in ("registration", "appointment", "consultation"):
            self.clock.sleep(LOCAL_STEP_MS / 1000.0)
            steps.append({"step": local, "status": "SUCCESS", "core_ok": True, "partner": None})
        failed_step, degraded = None, []
        for partner in PARTNERS:
            r = self.execute_partner(partner, DEFAULT_OPERATION[partner], {"patient_id": patient_id},
                                     mode=mode, request_id=f"{visit_id}-{partner}", source=source)
            steps.append({"step": partner, "status": r["status"], "core_ok": r["core_ok"], "partner": partner,
                          "retry_count": r["retry_count"], "fallback_used": r["fallback_used"],
                          "latency_ms": r["latency_ms"], "message": r["message"]})
            if not r["core_ok"]:
                failed_step = partner
                break
            if r["fallback_used"]:
                degraded.append(partner)
        duration_ms = round((self.clock.time() - start) * 1000.0, 1)
        status = "FAILED" if failed_step else ("COMPLETED_DEGRADED" if degraded else "COMPLETED")
        return {"visit_id": visit_id, "patient_id": patient_id, "mode": mode, "core_ok": failed_step is None,
                "status": status, "duration_ms": duration_ms, "failed_step": failed_step,
                "degraded_steps": degraded, "steps": steps, "t_start": start, "t_end": self.clock.time()}

    # ------------------------------------------------------- failure simulation
    def simulate(self, partner, mode, latency_ms=None, error_rate=None, duration_seconds=None):
        mode = mode.upper()
        if mode in ("NORMAL", "RECOVERY"):
            return self.recover(partner)
        state = self.simulator.set_mode(partner, mode, latency_ms, error_rate, duration_seconds)
        if self.db:
            self._close_open_event(partner, recovery_time=0.0, note="replaced by a new simulation")
            desc = f"Simulated {mode} on {partner}" + (f" (latency {latency_ms} ms)" if latency_ms else "") \
                   + (f" (error rate {error_rate})" if error_rate is not None else "") \
                   + (f" for {duration_seconds}s" if duration_seconds else "")
            self._open_event[partner] = self.db.execute(
                "INSERT INTO failure_events(timestamp,partner,failure_type,severity,description,resolved) VALUES (?,?,?,?,?,0)",
                (self.clock.now_iso(), partner, mode, SEVERITY.get(mode, "low"), desc))
            self.db.update_partner_row(partner, last_failure=self.clock.now_iso())
        return self.simulator.get_state(partner)

    def recover(self, partner):
        was = self.simulator.recover(partner)
        self._handle_recovered(partner)
        return {**self.simulator.get_state(partner), "previous_mode": was}

    def _on_sim_expire(self, partner):
        self._handle_recovered(partner)

    def _handle_recovered(self, partner):
        if not self.db:
            return
        self.db.update_partner_row(partner, last_recovery=self.clock.now_iso())
        eid = self._open_event.pop(partner, None)
        if eid is None:
            return
        if self.resilience.breakers[partner].state == "CLOSED":
            self.db.execute("UPDATE failure_events SET resolved=1, recovery_time=0.0 WHERE id=?", (eid,))
        else:   # recovery time = recovered -> circuit CLOSED again
            self._awaiting_close[partner] = (eid, self.clock.time())

    def _close_open_event(self, partner, recovery_time, note=None):
        eid = self._open_event.pop(partner, None)
        if eid is not None:
            self.db.execute("UPDATE failure_events SET resolved=1, recovery_time=?, description=description||? WHERE id=?",
                            (recovery_time, f" [{note}]" if note else "", eid))

    def _on_transition(self, partner, old, new, reason, t):
        self.recorder.record_circuit_event(partner, old, new, reason, self.clock.now_iso(), t=t, source=self.source)
        if not self.db:
            return
        self.db.update_partner_row(partner, circuit_state=new)
        if new == "OPEN":
            self.db.update_partner_row(partner, last_failure=self.clock.now_iso())
        if new == "CLOSED":
            self.db.update_partner_row(partner, last_recovery=self.clock.now_iso())
            if partner in self._awaiting_close:
                eid, rec_at = self._awaiting_close.pop(partner)
                self.db.execute("UPDATE failure_events SET resolved=1, recovery_time=? WHERE id=?",
                                (round(t - rec_at, 2), eid))

    # ------------------------------------------------------------ health / map
    def _refresh_partner_row(self, partner, result):
        if not self.db:
            return
        fields = {"circuit_state": result["circuit_state"] if result["mode"] == "resilient" else None}
        fields = {k: v for k, v in fields.items() if v is not None}
        if result["fallback_used"] or not result["core_ok"]:
            fields["last_failure"] = result["timestamp"]
        if result["status"] == "RECOVERED":
            fields["last_recovery"] = result["timestamp"]
        fields["status"] = self.partner_health(partner)["status"]
        self.db.update_partner_row(partner, **fields)

    def probe(self, partner):
        """Active health check (bypasses the circuit breaker; recorded as operation 'health_check')."""
        from src.partners.partner_simulator import PartnerTimeout
        timeout = self.resilience.timeouts.for_partner(partner)
        t0 = self.clock.time()
        try:
            resp = self.simulator.call(partner, "health_check", {}, timeout, f"probe-{uuid.uuid4().hex[:6]}")
            ok, code, etype = resp.ok, resp.status_code, resp.error_type
        except PartnerTimeout:
            ok, code, etype = False, None, "TIMEOUT"
        lat = round((self.clock.time() - t0) * 1000.0, 1)
        res = {"request_id": f"PROBE-{uuid.uuid4().hex[:6].upper()}", "timestamp": self.clock.now_iso(),
               "partner": partner, "operation": "health_check", "latency_ms": lat, "success": ok,
               "status": "SUCCESS" if ok else "TIMEOUT" if etype == "TIMEOUT" else "DEGRADED",
               "error_type": etype, "retry_count": 0, "circuit_state": self.resilience.breakers[partner].state,
               "fallback_used": False, "mode": "probe", "core_ok": True, "status_code": code, "attempts": []}
        self.recorder.record_call(res, "probe")
        return res

    def partner_health(self, partner):
        window = self.config["monitoring"]["health_window_seconds"]
        recent = self.recorder.recent_calls(partner, limit=10, since_iso=self.clock.iso_ago(window))
        h = compute_health(recent, self.resilience.breakers[partner].info(),
                           self.resilience.timeouts.for_partner(partner))
        h["partner"] = partner
        return h

    def partners_overview(self):
        out = {}
        for p in PARTNERS:
            h = self.partner_health(p)
            h["circuit"] = self.resilience.breakers[p].info()
            h["simulation"] = self.simulator.get_state(p)
            h["timeout_seconds"] = self.resilience.timeouts.for_partner(p)
            h["display_name"] = self.config["partners"][p]["name"]
            out[p] = h
        return out

    def dependency_map(self):
        impact = {
            "laboratory": "New lab orders are recorded for later sync; existing records stay available.",
            "pharmacy": "Prescription data cannot be refreshed; the visit continues.",
            "insurance": "Eligibility stays PENDING; the visit continues and verification is deferred.",
            "telemedicine": "Booking is not created; the clinician is asked to try again later.",
        }
        nodes = [{"id": "core", "label": "Hospital Core", "status": "HEALTHY", "color": "green", "critical": True}]
        edges = []
        overall = "HEALTHY"
        for p in PARTNERS:
            h = self.partner_health(p)
            nodes.append({"id": p, "label": self.config["partners"][p]["name"], "status": h["status"],
                          "color": h["color"], "circuit_state": self.resilience.breakers[p].state,
                          "avg_latency_ms": h["avg_latency_ms"], "impact": impact[p], "critical": False})
            edges.append({"from": "core", "to": p, "type": "non-critical (graceful degradation)"})
            if h["status"] in ("UNAVAILABLE", "CIRCUIT_OPEN", "DEGRADED"):
                overall = "DEGRADED"
        nodes[0]["status"] = overall
        nodes[0]["color"] = COLORS[overall]
        return {"nodes": nodes, "edges": edges}
