"""Resilience pipeline wrapped around every partner call.

    circuit breaker check -> call with per-partner timeout -> classify outcome
        -> controlled retry (transient only, bounded, back-off)
        -> record result in breaker -> truthful fallback if the operation cannot complete

Time is read only from the injected clock, so the same code runs live and in fast simulations.
"""
from src.partners.partner_simulator import PARTNERS, PartnerTimeout
from src.resilience.circuit_breaker import CircuitBreaker, CircuitState
from src.resilience.errors import TIMEOUT, classify, counts_as_partner_failure
from src.resilience.fallback import FallbackManager
from src.resilience.result import build_result
from src.resilience.retry import RetryPolicy
from src.resilience.timeout import TimeoutPolicy


class ResilienceManager:
    def __init__(self, config: dict, clock, call_fn, on_circuit_transition=None):
        res = config["resilience"]
        self.clock = clock
        self.call_fn = call_fn               # call_fn(partner, operation, payload, timeout_seconds, request_key)
        self.timeouts = TimeoutPolicy(res["timeout"])
        self.retry = RetryPolicy(**res["retry"])
        cb = res["circuit_breaker"]
        self.breakers = {
            p: CircuitBreaker(p, cb["failure_threshold"], cb["recovery_timeout_seconds"],
                              cb["half_open_max_calls"], clock, on_circuit_transition)
            for p in PARTNERS
        }
        self.fallbacks = FallbackManager(config.get("fallbacks"))

    def reconfigure(self, config: dict):
        """Apply new rules in place; keeps each breaker's current state."""
        res = config["resilience"]
        self.timeouts = TimeoutPolicy(res["timeout"])
        self.retry = RetryPolicy(**res["retry"])
        cb = res["circuit_breaker"]
        for b in self.breakers.values():
            b.failure_threshold = int(cb["failure_threshold"])
            b.recovery_timeout_seconds = float(cb["recovery_timeout_seconds"])
            b.half_open_max_calls = int(cb["half_open_max_calls"])
        self.fallbacks = FallbackManager(config.get("fallbacks"))

    # ------------------------------------------------------------------ helpers
    def circuit_info(self):
        return {p: b.info() for p, b in self.breakers.items()}

    @staticmethod
    def _failure_status(blocked_first, error_type, status_code):
        if blocked_first:
            return "CIRCUIT_OPEN"
        if error_type == TIMEOUT:
            return "TIMEOUT"
        if status_code == 503:
            return "TEMPORARILY_UNAVAILABLE"
        if status_code in (502, 504):
            return "DEGRADED"
        return "FALLBACK_ACTIVE"

    # --------------------------------------------------------------------- main
    def execute(self, partner, operation, payload, request_id) -> dict:
        cb = self.breakers[partner]
        timeout = self.timeouts.for_partner(partner)
        start = self.clock.time()
        attempts, retries = [], 0
        last = {"error_type": None, "status_code": None, "category": None}
        trial_call = False
        outcome = None          # "SUCCESS" | "REJECTED" | "FAILED"
        blocked_first = False
        body = {}

        while True:
            if not cb.allow_request():
                blocked_first = not attempts
                outcome = "FAILED"
                break
            if cb.state == CircuitState.HALF_OPEN:
                trial_call = True
            n = len(attempts) + 1
            t0 = self.clock.time()
            try:
                resp = self.call_fn(partner, operation, payload, timeout, f"{request_id}#{n}")
                category, etype = classify(resp.status_code)
                code, body = resp.status_code, resp.body
            except PartnerTimeout:
                category, etype = classify(timed_out=True)
                code, body = None, {}
            latency = round((self.clock.time() - t0) * 1000.0, 1)
            att = {"attempt": n, "result": "SUCCESS" if category == "SUCCESS" else etype,
                   "status_code": code, "latency_ms": latency, "outcome": None}
            last = {"error_type": etype, "status_code": code, "category": category}

            if category == "SUCCESS":
                cb.record_success()
                att["outcome"] = "SUCCESS"
                att["circuit_state"] = cb.state
                attempts.append(att)
                outcome = "SUCCESS"
                break
            if not counts_as_partner_failure(category):      # 4xx: caller's problem, no retry, no fallback
                cb.record_ignored()
                att["outcome"] = "REJECTED"
                att["circuit_state"] = cb.state
                attempts.append(att)
                outcome = "REJECTED"
                break
            cb.record_failure()
            att["circuit_state"] = cb.state
            if self.retry.may_retry(category, retries) and cb.state != CircuitState.OPEN:
                att["outcome"] = "RETRYING"
                attempts.append(att)
                retries += 1
                self.clock.sleep(self.retry.delay_before(retries))
                continue
            att["outcome"] = "FAILED"
            attempts.append(att)
            outcome = "FAILED"
            break

        total_ms = round((self.clock.time() - start) * 1000.0, 1)
        base = dict(request_id=request_id, partner=partner, operation=operation, mode="resilient",
                    retry_count=retries, attempt_count=len(attempts), attempts=attempts,
                    circuit_state=cb.state, circuit_blocked=blocked_first, latency_ms=total_ms,
                    error_type=None if outcome == "SUCCESS" else last["error_type"],
                    status_code=200 if outcome == "SUCCESS" else last["status_code"])
        label = partner.capitalize()

        if outcome == "SUCCESS":
            recovered = retries > 0 or trial_call
            if trial_call and retries == 0:
                msg = f"{label} service has recovered. Request completed."
            elif retries > 0:
                msg = f"{label} request completed after {retries} retr{'y' if retries == 1 else 'ies'}."
            else:
                msg = f"{label} request completed."
            return build_result(**base, status="RECOVERED" if recovered else "SUCCESS", success=True,
                                core_ok=True, message=msg, data=body)
        if outcome == "REJECTED":
            return build_result(**base, status="REJECTED", success=False, core_ok=True,
                                message="The request was rejected as invalid. Please correct it and try again "
                                        "(not retried, partner health unaffected).", reason="non-retryable")
        # FAILED -> truthful fallback
        status = self._failure_status(blocked_first, last["error_type"], last["status_code"])
        reason = ("circuit breaker OPEN - failing fast" if blocked_first
                  else f"{last['error_type']} after {retries} retr{'y' if retries == 1 else 'ies'}")
        fb = self.fallbacks.build(partner, reason)
        return build_result(**base, status=status, success=False, core_ok=True, fallback_used=True,
                            message=fb["message"], data=fb["data"], queue_for_sync=fb["queue_for_sync"],
                            reason=reason)
