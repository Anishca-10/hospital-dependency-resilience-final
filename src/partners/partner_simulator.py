"""Simulated external partner services (Laboratory, Pharmacy, Insurance, Telemedicine).

Behaviour is driven by real state, not labels:
  * latency_ms / failure_rate come from the configuration,
  * failure modes (HIGH_LATENCY, TIMEOUT, INTERMITTENT, CONTINUOUS_FAILURE, UNAVAILABLE)
    change what actual calls do (sleep time, HTTP status),
  * a caller-supplied timeout is enforced like an HTTP-client socket timeout: the call
    waits ``timeout`` seconds and raises PartnerTimeout if the partner is slower.

Randomness is derived from (seed, partner, request_key) so two systems that issue the
same logical request see the same partner behaviour (needed for fair experiments).
"""
import random
import threading
from dataclasses import dataclass, field

from src.partners import insurance, laboratory, pharmacy, telemedicine

BUILDERS = {m.PARTNER: m for m in (laboratory, pharmacy, insurance, telemedicine)}
PARTNERS = list(BUILDERS)

MODES = ["NORMAL", "HIGH_LATENCY", "TIMEOUT", "INTERMITTENT", "CONTINUOUS_FAILURE", "UNAVAILABLE"]
TRANSIENT_STATUSES = [503, 502, 504]
HANG_LATENCY_MS = 30000.0       # a "hung" partner: effectively never answers within a sane timeout
UNAVAILABLE_LATENCY_MS = 50.0   # connection refused / gateway error returns fast


class PartnerTimeout(Exception):
    """The caller's timeout elapsed before the partner answered."""

    def __init__(self, partner, timeout_seconds):
        super().__init__(f"{partner} did not respond within {timeout_seconds}s")
        self.partner = partner
        self.timeout_seconds = timeout_seconds


@dataclass
class PartnerResponse:
    status_code: int
    body: dict
    latency_ms: float
    error_type: str = None   # None on success, otherwise e.g. HTTP_503, HTTP_400
    meta: dict = field(default_factory=dict)

    @property
    def ok(self):
        return self.status_code == 200


class PartnerSimulator:
    def __init__(self, config: dict, clock, seed: int = 0, on_expire=None):
        self.clock = clock
        self.seed = seed
        self.on_expire = on_expire
        self._lock = threading.RLock()
        self._counter = 0
        self.states = {}
        for p in PARTNERS:
            self.states[p] = {
                "partner": p, "mode": "NORMAL", "base_latency_ms": 300.0, "failure_rate": 0.0,
                "sim_latency_ms": None, "sim_error_rate": None, "expires_at": None,
                "script": [], "calls": 0, "failures": 0, "started_at": None,
            }
        self.apply_config(config)

    # ------------------------------------------------------------- configuration
    def apply_config(self, config: dict):
        with self._lock:
            for p, cfg in config["partners"].items():
                if p in self.states:
                    self.states[p]["base_latency_ms"] = float(cfg["latency_ms"])
                    self.states[p]["failure_rate"] = float(cfg["failure_rate"])

    def set_mode(self, partner, mode, latency_ms=None, error_rate=None, duration_seconds=None):
        mode = mode.upper()
        if partner not in self.states:
            raise ValueError(f"Unknown partner: {partner}")
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode}; choose one of {MODES}")
        with self._lock:
            st = self.states[partner]
            st["mode"] = mode
            st["sim_latency_ms"] = float(latency_ms) if latency_ms not in (None, "", 0) else None
            st["sim_error_rate"] = float(error_rate) if error_rate not in (None, "") else None
            st["expires_at"] = (self.clock.time() + float(duration_seconds)) if duration_seconds else None
            st["started_at"] = self.clock.time() if mode != "NORMAL" else None
            return dict(st)

    def recover(self, partner):
        with self._lock:
            st = self.states[partner]
            was = st["mode"]
            st.update(mode="NORMAL", sim_latency_ms=None, sim_error_rate=None, expires_at=None, script=[], started_at=None)
            return was

    def script(self, partner, outcomes):
        """Queue deterministic outcomes consumed one per call: 'OK','TIMEOUT','502','503','504','500'."""
        with self._lock:
            self.states[partner]["script"] = list(outcomes)

    def get_state(self, partner) -> dict:
        self._check_expiry(partner)
        with self._lock:
            st = dict(self.states[partner])
            st["script_remaining"] = len(st.pop("script"))
            st["remaining_seconds"] = (round(max(0.0, st["expires_at"] - self.clock.time()), 1)
                                       if st["expires_at"] else None)
            return st

    def _check_expiry(self, partner):
        fire = False
        with self._lock:
            st = self.states[partner]
            if st["expires_at"] is not None and self.clock.time() >= st["expires_at"]:
                self.recover(partner)
                fire = True
        if fire and self.on_expire:
            self.on_expire(partner)

    # ---------------------------------------------------------------- the call
    def _rng(self, partner, request_key):
        if request_key is None:
            with self._lock:
                self._counter += 1
                request_key = f"auto-{self._counter}"
        return random.Random(f"{self.seed}|{partner}|{request_key}")

    def _plan(self, st, rng):
        """Decide (latency_ms, status_or_None). status None => success."""
        j = 1.0 + rng.uniform(-0.05, 0.05)
        base = st["base_latency_ms"] * j
        pick_err = lambda: rng.choices(TRANSIENT_STATUSES, weights=[6, 3, 1])[0]
        if st["script"]:
            tok = str(st["script"].pop(0)).upper()
            if tok == "OK":
                return base, None
            if tok == "TIMEOUT":
                return HANG_LATENCY_MS, None
            return base, int(tok)
        mode = st["mode"]
        err_rate = st["sim_error_rate"] if st["sim_error_rate"] is not None else st["failure_rate"]
        if mode == "UNAVAILABLE":
            return UNAVAILABLE_LATENCY_MS, 503
        if mode == "CONTINUOUS_FAILURE":
            return base, 502
        if mode == "TIMEOUT":
            return max(st["sim_latency_ms"] or 0.0, HANG_LATENCY_MS), None
        if mode == "HIGH_LATENCY":
            lat = (st["sim_latency_ms"] or 5000.0) * j
            return lat, (pick_err() if rng.random() < err_rate else None)
        if mode == "INTERMITTENT":
            # failing calls are a realistic mix: ~35% hang (client sees a timeout), the rest are 502/503/504
            rate = st["sim_error_rate"] if st["sim_error_rate"] is not None else 0.5
            if rng.random() < rate:
                return (HANG_LATENCY_MS, None) if rng.random() < 0.35 else (base, pick_err())
            return base, None
        return base, (pick_err() if rng.random() < err_rate else None)  # NORMAL

    def call(self, partner, operation, payload=None, timeout_seconds=None, request_key=None) -> PartnerResponse:
        """Execute one call. Sleeps on the configured clock. Raises PartnerTimeout."""
        if partner not in BUILDERS:
            raise ValueError(f"Unknown partner: {partner}")
        payload = payload or {}
        self._check_expiry(partner)
        rng = self._rng(partner, request_key)
        with self._lock:
            st = self.states[partner]
            st["calls"] += 1
            # Partner-side validation (a permanent, non-retryable error class).
            if operation != "health_check" and not payload.get("patient_id"):
                latency_ms, status = 20.0, 400
                invalid = True
            else:
                latency_ms, status = self._plan(st, rng)
                invalid = False
        if timeout_seconds is not None and latency_ms / 1000.0 > timeout_seconds:
            self.clock.sleep(timeout_seconds)
            with self._lock:
                self.states[partner]["failures"] += 1
            raise PartnerTimeout(partner, timeout_seconds)
        self.clock.sleep(latency_ms / 1000.0)
        latency_ms = round(latency_ms, 1)
        if invalid:
            with self._lock:
                self.states[partner]["failures"] += 1
            return PartnerResponse(400, {"success": False, "code": "VALIDATION_ERROR",
                                         "error": "patient_id is required"}, latency_ms, "HTTP_400")
        if status is not None:
            with self._lock:
                self.states[partner]["failures"] += 1
            return PartnerResponse(status, {"success": False, "code": f"HTTP_{status}",
                                            "error": f"{partner} returned HTTP {status}"}, latency_ms, f"HTTP_{status}")
        body = {"success": True, "partner": partner, "operation": operation}
        if operation == "health_check":
            body["pong"] = True
        else:
            body.update(BUILDERS[partner].build_response(operation, payload, rng))
        return PartnerResponse(200, body, latency_ms, None)
