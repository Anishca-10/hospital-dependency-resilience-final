"""Uniform result structure returned for every partner request (resilient or baseline)."""


def build_result(*args, **kw) -> dict:
    res = {
        "request_id": None, "partner": None, "operation": None, "mode": None, "timestamp": None,
        "status": None, "success": False, "core_ok": False, "fallback_used": False,
        "message": "", "retry_count": 0, "attempt_count": 0, "attempts": [],
        "circuit_state": "N/A", "circuit_blocked": False, "latency_ms": 0.0,
        "error_type": None, "status_code": None, "data": {}, "queue_for_sync": False, "reason": None,
    }
    res.update(kw)
    return res
