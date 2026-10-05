"""Controlled retry policy: bounded attempts, exponential back-off, transient errors only."""


class RetryPolicy:
    def __init__(self, enabled=True, max_attempts=2, backoff_seconds=0.2, backoff_multiplier=2.0):
        self.enabled = bool(enabled)
        self.max_attempts = int(max_attempts)          # retries AFTER the first call
        self.backoff_seconds = float(backoff_seconds)
        self.backoff_multiplier = float(backoff_multiplier)

    def delay_before(self, retry_number: int) -> float:
        """Delay before retry #retry_number (1-based)."""
        return self.backoff_seconds * (self.backoff_multiplier ** (retry_number - 1))

    def may_retry(self, category: str, retries_done: int) -> bool:
        """Only TRANSIENT failures are retried, never beyond max_attempts."""
        return self.enabled and category == "TRANSIENT" and retries_done < self.max_attempts
