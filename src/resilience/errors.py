"""Failure classification shared by the resilience layer and the baseline."""

RETRYABLE_STATUS = {502, 503, 504}          # transient gateway / availability errors
STATUS_VOCABULARY = [
    "SUCCESS", "DEGRADED", "TIMEOUT", "RETRYING", "CIRCUIT_OPEN",
    "FALLBACK_ACTIVE", "RECOVERED", "TEMPORARILY_UNAVAILABLE",
]

TIMEOUT = "TIMEOUT"


def classify(status_code=None, timed_out=False):
    """Return (category, error_type).

    category:
      SUCCESS    - 2xx
      TRANSIENT  - timeout / 502 / 503 / 504  (retryable, counts toward circuit breaker)
      SERVER     - other 5xx (not retried, still counts as a partner failure)
      PERMANENT  - 4xx: invalid request, validation, authentication (never retried,
                   not a partner-health signal, no fallback - the caller must fix the request)
    """
    if timed_out:
        return "TRANSIENT", TIMEOUT
    if status_code is None:
        return "SERVER", "UNKNOWN"
    if 200 <= status_code < 300:
        return "SUCCESS", None
    if status_code in RETRYABLE_STATUS:
        return "TRANSIENT", f"HTTP_{status_code}"
    if 400 <= status_code < 500:
        return "PERMANENT", f"HTTP_{status_code}"
    return "SERVER", f"HTTP_{status_code}"


def counts_as_partner_failure(category):
    return category in ("TRANSIENT", "SERVER")
