"""Per-partner timeout policy (values come from configuration, never hard-coded)."""


class TimeoutPolicy:
    def __init__(self, timeouts: dict, default: float = 2.0):
        self.timeouts = {k.lower(): float(v) for k, v in (timeouts or {}).items()}
        self.default = float(default)

    def for_partner(self, partner: str) -> float:
        return self.timeouts.get(partner.lower(), self.default)
