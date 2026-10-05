"""Single source of truth for metric formulas (used by the live dashboard AND the experiments)."""
import numpy as np

SUCCESS_STATUSES = ("SUCCESS", "RECOVERED")


def pct(num, den):
    return round(100.0 * num / den, 2) if den else None


def compute_metrics(calls, attempts=(), events=()):
    """Request-level metrics.

    core availability = core requests that completed without an error reaching the core application
                        / all core requests * 100
    request success   = partner operation completed normally (SUCCESS or RECOVERED, i.e. no fallback)
    """
    calls = [c for c in calls if c.get("operation") != "health_check"]
    n = len(calls)
    lat = [float(c["latency_ms"]) for c in calls]
    ok = sum(1 for c in calls if c["core_ok"])
    succ = sum(1 for c in calls if c["status"] in SUCCESS_STATUSES)
    status_counts = {}
    for c in calls:
        status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
    return {
        "total_requests": n,
        "core_ok_requests": ok,
        "core_availability_pct": pct(ok, n),
        "successful_requests": succ,
        "request_success_rate_pct": pct(succ, n),
        "failed_requests": n - succ,
        "request_failure_rate_pct": pct(n - succ, n),
        "errors_propagated_to_core": n - ok,
        "avg_latency_ms": round(float(np.mean(lat)), 1) if lat else None,
        "p95_latency_ms": round(float(np.percentile(lat, 95)), 1) if lat else None,
        "timeout_count": sum(1 for a in attempts if a.get("result") == "TIMEOUT"),
        "retry_count": int(sum(c["retry_count"] for c in calls)),
        "fallback_count": sum(1 for c in calls if c["fallback_used"]),
        "circuit_open_count": sum(1 for e in events if e["new_state"] == "OPEN"),
        "fail_fast_count": status_counts.get("CIRCUIT_OPEN", 0),
        "status_counts": status_counts,
    }
