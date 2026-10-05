"""SIMPLE BASELINE: what a straightforward integration typically looks like.

  * direct, synchronous call to the partner, default client timeout (config: baseline.timeout_seconds)
  * ONE immediate retry on timeout / 5xx (config: baseline.max_retries), no back-off
  * NO circuit breaker, NO fallback, NO per-partner tuning
  * if the partner call ultimately fails, the error propagates to the core workflow

It is deliberately a *reasonable* baseline (it has a timeout and a retry), not a strawman.
"""
from src.partners.partner_simulator import PartnerTimeout
from src.resilience.errors import classify
from src.resilience.result import build_result


class BaselineClient:
    def __init__(self, config: dict, clock, call_fn):
        self.clock = clock
        self.call_fn = call_fn
        self.timeout = float(config["baseline"]["timeout_seconds"])
        self.max_retries = int(config["baseline"]["max_retries"])

    def execute(self, partner, operation, payload, request_id) -> dict:
        start = self.clock.time()
        attempts, retries = [], 0
        body, last = {}, (None, None)
        success = False
        while True:
            n = len(attempts) + 1
            t0 = self.clock.time()
            try:
                resp = self.call_fn(partner, operation, payload, self.timeout, f"{request_id}#{n}")
                category, etype = classify(resp.status_code)
                code, body = resp.status_code, resp.body
            except PartnerTimeout:
                category, etype = classify(timed_out=True)
                code, body = None, {}
            lat = round((self.clock.time() - t0) * 1000.0, 1)
            attempts.append({"attempt": n, "result": "SUCCESS" if category == "SUCCESS" else etype,
                             "status_code": code, "latency_ms": lat,
                             "outcome": "SUCCESS" if category == "SUCCESS" else "FAILED",
                             "circuit_state": "N/A"})
            last = (etype, code)
            if category == "SUCCESS":
                success = True
                break
            if category in ("TRANSIENT", "SERVER") and retries < self.max_retries:
                retries += 1
                attempts[-1]["outcome"] = "RETRYING"
                continue
            break
        total = round((self.clock.time() - start) * 1000.0, 1)
        base = dict(request_id=request_id, partner=partner, operation=operation, mode="baseline",
                    retry_count=retries, attempt_count=len(attempts), attempts=attempts,
                    circuit_state="N/A", latency_ms=total, error_type=None if success else last[0],
                    status_code=200 if success else last[1])
        if success:
            return build_result(**base, status="SUCCESS", success=True, core_ok=True,
                                message=f"{partner.capitalize()} request completed.", data=body)
        return build_result(**base, status="ERROR", success=False, core_ok=False,
                            message=f"{partner.capitalize()} call failed ({last[0]}); error propagated to the core application.",
                            reason=str(last[0]))
