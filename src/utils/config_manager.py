"""Configuration management: load, validate, merge, persist config.yaml."""
import copy
import os
import threading

import yaml

PARTNERS = ["laboratory", "pharmacy", "insurance", "telemedicine"]

DEFAULT_FALLBACKS = {
    "laboratory": {
        "status": "TEMPORARILY_UNAVAILABLE",
        "message": "Laboratory service is temporarily unavailable. Existing records remain accessible. "
                   "New laboratory results will be synchronized when the service recovers.",
    },
    "pharmacy": {
        "status": "TEMPORARILY_UNAVAILABLE",
        "message": "Pharmacy service is temporarily unavailable. Prescription information cannot be refreshed right now.",
    },
    "insurance": {
        "status": "DEGRADED",
        "message": "Insurance verification is temporarily unavailable. The request has been recorded for later verification.",
    },
    "telemedicine": {
        "status": "TEMPORARILY_UNAVAILABLE",
        "message": "Telemedicine scheduling is temporarily unavailable. Please try again later.",
    },
}

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 5000, "debug": False},
    "resilience": {
        "timeout": {"laboratory": 2.0, "pharmacy": 2.0, "insurance": 3.0, "telemedicine": 2.0},
        "retry": {"enabled": True, "max_attempts": 2, "backoff_seconds": 0.2, "backoff_multiplier": 2.0},
        "circuit_breaker": {"failure_threshold": 3, "recovery_timeout_seconds": 10.0, "half_open_max_calls": 1},
    },
    "baseline": {"timeout_seconds": 10.0, "max_retries": 1},
    "partners": {
        "laboratory": {"name": "Laboratory", "latency_ms": 300, "failure_rate": 0.05},
        "pharmacy": {"name": "Pharmacy", "latency_ms": 400, "failure_rate": 0.05},
        "insurance": {"name": "Insurance", "latency_ms": 500, "failure_rate": 0.05},
        "telemedicine": {"name": "Telemedicine", "latency_ms": 350, "failure_rate": 0.05},
    },
    "fallbacks": DEFAULT_FALLBACKS,
    "monitoring": {"probe_interval_seconds": 15, "health_window_seconds": 60},
    "experiments": {
        "seeds": [11, 12, 13, 14, 15],
        "visits_per_scenario": 60,
        "visit_interval_seconds": 5.0,
        "target_core_availability_pct": 95.0,
        "latency_slo_seconds": 5.0,
    },
}


class ConfigError(ValueError):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [str(errors)]
        super().__init__("; ".join(self.errors))


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def parse_rate(value):
    """Accept 0..1 (fraction) or '25%' strings; returns a float fraction or raises ValueError."""
    if isinstance(value, str):
        v = value.strip()
        if v.endswith("%"):
            return float(v[:-1]) / 100.0
        return float(v)
    return float(value)


def _num(errors, label, value, lo=None, hi=None, integer=False, lo_exclusive=False):
    try:
        if isinstance(value, bool):
            raise ValueError
        num = int(value) if integer and float(value) == int(float(value)) else float(value)
        if integer and num != int(num):
            raise ValueError
    except (TypeError, ValueError):
        errors.append(f"{label} must be a {'whole number' if integer else 'number'}")
        return None
    if lo is not None and (num <= lo if lo_exclusive else num < lo):
        errors.append(f"{label} must be {'>' if lo_exclusive else '>='} {lo}")
    if hi is not None and num > hi:
        errors.append(f"{label} must be <= {hi}")
    return num


def validate_and_normalize(cfg: dict) -> dict:
    """Validate a FULL config dict; returns a normalised copy or raises ConfigError."""
    errors = []
    out = copy.deepcopy(cfg)
    res = out.get("resilience", {})
    for p in PARTNERS:
        t = res.get("timeout", {}).get(p)
        n = _num(errors, f"timeout.{p}", t, lo=0, hi=60, lo_exclusive=True)
        if n is not None:
            res["timeout"][p] = float(n)
        part = out.get("partners", {}).get(p, {})
        n = _num(errors, f"partners.{p}.latency_ms", part.get("latency_ms"), lo=0, hi=60000)
        if n is not None:
            part["latency_ms"] = float(n)
        try:
            rate = parse_rate(part.get("failure_rate"))
            if not 0.0 <= rate <= 1.0:
                raise ValueError
            part["failure_rate"] = rate
        except (TypeError, ValueError):
            errors.append(f"partners.{p}.failure_rate must be between 0 and 1 (or 0%-100%)")
    retry = res.get("retry", {})
    if not isinstance(retry.get("enabled"), bool):
        errors.append("retry.enabled must be true or false")
    n = _num(errors, "retry.max_attempts", retry.get("max_attempts"), lo=0, hi=5, integer=True)
    if n is not None:
        retry["max_attempts"] = int(n)
    n = _num(errors, "retry.backoff_seconds", retry.get("backoff_seconds"), lo=0, hi=30)
    if n is not None:
        retry["backoff_seconds"] = float(n)
    n = _num(errors, "retry.backoff_multiplier", retry.get("backoff_multiplier", 1.0), lo=1, hi=10)
    if n is not None:
        retry["backoff_multiplier"] = float(n)
    cb = res.get("circuit_breaker", {})
    n = _num(errors, "circuit_breaker.failure_threshold", cb.get("failure_threshold"), lo=1, hi=20, integer=True)
    if n is not None:
        cb["failure_threshold"] = int(n)
    n = _num(errors, "circuit_breaker.recovery_timeout_seconds", cb.get("recovery_timeout_seconds"), lo=0, hi=3600, lo_exclusive=True)
    if n is not None:
        cb["recovery_timeout_seconds"] = float(n)
    n = _num(errors, "circuit_breaker.half_open_max_calls", cb.get("half_open_max_calls"), lo=1, hi=10, integer=True)
    if n is not None:
        cb["half_open_max_calls"] = int(n)
    base = out.get("baseline", {})
    n = _num(errors, "baseline.timeout_seconds", base.get("timeout_seconds"), lo=0, hi=120, lo_exclusive=True)
    if n is not None:
        base["timeout_seconds"] = float(n)
    n = _num(errors, "baseline.max_retries", base.get("max_retries"), lo=0, hi=5, integer=True)
    if n is not None:
        base["max_retries"] = int(n)
    if errors:
        raise ConfigError(errors)
    return out


class ConfigManager:
    """Thread-safe holder of the active configuration, backed by a YAML file."""

    def __init__(self, path: str = "config/config.yaml", persist: bool = True):
        self.path = path
        self.persist = persist
        self._lock = threading.RLock()
        self.version = 0
        raw = {}
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        self._cfg = validate_and_normalize(deep_merge(DEFAULTS, raw))

    @classmethod
    def from_dict(cls, cfg: dict):
        """In-memory manager (never persisted) built from a config snapshot."""
        return cls(path=None, persist=False)._with(cfg)

    def _with(self, cfg: dict):
        self._cfg = validate_and_normalize(deep_merge(DEFAULTS, cfg))
        return self

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._cfg)

    def update(self, partial: dict) -> dict:
        """Merge ``partial`` into the active config, validate, persist. Raises ConfigError."""
        with self._lock:
            candidate = validate_and_normalize(deep_merge(self._cfg, partial))
            self._cfg = candidate
            self.version += 1
            if self.persist and self.path:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(self.path, "w", encoding="utf-8") as fh:
                    yaml.safe_dump(candidate, fh, sort_keys=False, default_flow_style=False)
            return copy.deepcopy(candidate)
