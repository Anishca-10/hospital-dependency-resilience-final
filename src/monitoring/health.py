"""Dependency health derived from OBSERVED behaviour (recent calls + circuit state)."""

COLORS = {"HEALTHY": "green", "DEGRADED": "yellow", "UNAVAILABLE": "red",
          "CIRCUIT_OPEN": "gray", "UNKNOWN": "blue"}

FRIENDLY = {
    "HEALTHY": "Operating normally.",
    "DEGRADED": "Slow or partially failing. Requests may be retried or use fallback.",
    "UNAVAILABLE": "Not responding. Fallback behaviour is in effect.",
    "CIRCUIT_OPEN": "Protection active: requests are not sent to this service until it is tested again.",
    "UNKNOWN": "No recent activity to judge from.",
}


def compute_health(recent_calls, breaker_info, timeout_seconds):
    state = breaker_info["state"]
    n = len(recent_calls)
    fails = sum(1 for c in recent_calls if not c["success"])
    retried = sum(1 for c in recent_calls if c["retry_count"] > 0)
    avg_lat = (sum(c["latency_ms"] for c in recent_calls) / n) if n else 0.0
    fail_ratio = fails / n if n else 0.0
    if state == "OPEN":
        status = "CIRCUIT_OPEN"
    elif state == "HALF_OPEN":
        status = "DEGRADED"
    elif n == 0:
        status = "UNKNOWN"
    elif fail_ratio >= 0.8:
        status = "UNAVAILABLE"
    elif fail_ratio >= 0.2 or retried / n >= 0.3 or avg_lat > 0.8 * timeout_seconds * 1000:
        status = "DEGRADED"
    else:
        status = "HEALTHY"
    return {"status": status, "color": COLORS[status], "message": FRIENDLY[status],
            "recent_calls": n, "failure_ratio": round(fail_ratio, 2), "avg_latency_ms": round(avg_lat, 1),
            "last_checked": recent_calls[-1]["timestamp"] if n else None}
