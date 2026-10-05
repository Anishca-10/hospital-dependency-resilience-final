"""Experiment scenarios.

Every scenario is a timeline of fault-injection events keyed by VISIT INDEX, so the baseline and the
resilient system face the identical workload and identical partner conditions.
Event = (visit_index, partner, action, params). Actions: 'set' (simulate) or 'recover'.
"""
FAULT_START = 5   # first 5 visits are healthy in every scenario (warm-up / steady state)

SCENARIOS = [
    {"id": "S1", "name": "Normal operation", "events": [],
     "description": "No injected fault. Partners run with the configured background failure rate."},
    {"id": "S2", "name": "Laboratory high latency",
     "events": [(FAULT_START, "laboratory", "set", {"mode": "HIGH_LATENCY", "latency_ms": 5000})],
     "description": "Laboratory answers correctly but takes ~5000 ms."},
    {"id": "S3", "name": "Pharmacy intermittent failure",
     "events": [(FAULT_START, "pharmacy", "set", {"mode": "INTERMITTENT", "error_rate": 0.5})],
     "description": "50% of pharmacy calls fail (mix of timeouts and 502/503/504)."},
    {"id": "S4", "name": "Insurance complete outage",
     "events": [(FAULT_START, "insurance", "set", {"mode": "UNAVAILABLE"})],
     "description": "Insurance returns HTTP 503 for every call until the end of the run."},
    {"id": "S5", "name": "Telemedicine timeout",
     "events": [(FAULT_START, "telemedicine", "set", {"mode": "TIMEOUT"})],
     "description": "Telemedicine accepts the connection but never answers (hang)."},
    {"id": "S6", "name": "Partner recovery",
     "events": [(FAULT_START, "pharmacy", "set", {"mode": "UNAVAILABLE"}), (25, "pharmacy", "recover", {})],
     "recovery": {"partner": "pharmacy", "visit": 25},
     "description": "Pharmacy is down for visits 5-24, then recovers; measures time to normal operation."},
    {"id": "S7", "name": "Insurance transient failures",
     "events": [(FAULT_START, "insurance", "set", {"mode": "INTERMITTENT", "error_rate": 0.6})],
     "description": "60% of insurance calls fail transiently, so retries can succeed (retry demonstration)."},
    {"id": "S8", "name": "Laboratory consecutive failures",
     "events": [(FAULT_START, "laboratory", "set", {"mode": "CONTINUOUS_FAILURE"}), (35, "laboratory", "recover", {})],
     "recovery": {"partner": "laboratory", "visit": 35},
     "description": "Laboratory returns 502 on every call for visits 5-34: retries, breaker opening, fail-fast, "
                    "failed HALF_OPEN trials, then recovery."},
]
