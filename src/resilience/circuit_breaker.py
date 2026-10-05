"""Circuit breaker: a real CLOSED -> OPEN -> HALF_OPEN state machine.

CLOSED     calls flow; ``failure_threshold`` CONSECUTIVE failures trip the breaker.
OPEN       calls are rejected immediately (fail fast) until ``recovery_timeout_seconds`` passed.
HALF_OPEN  after the timeout, up to ``half_open_max_calls`` trial calls are allowed.
           A trial success closes the circuit; a trial failure re-opens it.
"""
import threading


class CircuitState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout_seconds=10.0,
                 half_open_max_calls=1, clock=None, on_transition=None):
        self.name = name
        self.failure_threshold = int(failure_threshold)
        self.recovery_timeout_seconds = float(recovery_timeout_seconds)
        self.half_open_max_calls = int(half_open_max_calls)
        self.clock = clock
        self.on_transition = on_transition   # callback(name, old, new, reason, timestamp)
        self._lock = threading.RLock()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at = None
        self.last_state_change = clock.time()
        self._half_open_inflight = 0
        self._half_open_successes = 0
        self.open_count = 0         # number of times the circuit tripped to OPEN
        self.rejected_count = 0     # calls failed fast while OPEN / HALF_OPEN-saturated

    # -- internal
    def _transition(self, new_state, reason):
        old = self.state
        if old == new_state:
            return
        self.state = new_state
        now = self.clock.time()
        self.last_state_change = now
        if new_state == CircuitState.OPEN:
            self.opened_at = now
            self.open_count += 1
        if new_state in (CircuitState.OPEN, CircuitState.CLOSED):
            self._half_open_inflight = 0
            self._half_open_successes = 0
        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
        if self.on_transition:
            self.on_transition(self.name, old, new_state, reason, now)

    # -- public API
    def allow_request(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if self.clock.time() - self.opened_at >= self.recovery_timeout_seconds:
                    self._transition(CircuitState.HALF_OPEN, "recovery timeout elapsed")
                else:
                    self.rejected_count += 1
                    return False
            # HALF_OPEN: limited number of trial calls
            if self._half_open_inflight < self.half_open_max_calls:
                self._half_open_inflight += 1
                return True
            self.rejected_count += 1
            return False

    def record_success(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                if self._half_open_successes >= self.half_open_max_calls:
                    self._transition(CircuitState.CLOSED, "trial call succeeded")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def record_failure(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN, "trial call failed")
            elif self.state == CircuitState.CLOSED:
                self.failure_count += 1
                if self.failure_count >= self.failure_threshold:
                    self._transition(CircuitState.OPEN, f"{self.failure_count} consecutive failures")

    def record_ignored(self):
        """A call finished with a non-health outcome (e.g. HTTP 400); free any HALF_OPEN trial slot."""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)

    def reset(self):
        with self._lock:
            self._transition(CircuitState.CLOSED, "manual reset")
            self.failure_count = 0

    def info(self) -> dict:
        with self._lock:
            now = self.clock.time()
            remaining = 0.0
            if self.state == CircuitState.OPEN:
                remaining = max(0.0, self.recovery_timeout_seconds - (now - self.opened_at))
            return {
                "name": self.name, "state": self.state, "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout_seconds,
                "remaining_open_seconds": round(remaining, 1),
                "time_in_state_seconds": round(now - self.last_state_change, 1),
                "open_count": self.open_count, "rejected_count": self.rejected_count,
            }
