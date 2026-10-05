"""Truthful fallbacks. A fallback never claims that the partner operation succeeded."""

# What each fallback actually does (these are real local behaviours, see HospitalCoreService):
#   queue=True  -> the request is stored in the pending_actions table and replayed on recovery.
FALLBACK_BEHAVIOUR = {
    "laboratory": {"queue": True, "data": {"existing_records_accessible": True,
                                           "new_request": "RECORDED_PENDING_SYNC"}},
    "pharmacy": {"queue": False, "data": {"prescription_refresh": "NOT_PERFORMED"}},
    "insurance": {"queue": True, "data": {"verification_status": "PENDING",
                                          "eligibility_confirmed": False}},
    "telemedicine": {"queue": False, "data": {"booking": "NOT_CREATED"}},
}


class FallbackManager:
    def __init__(self, fallbacks_config: dict):
        self.config = fallbacks_config or {}

    def build(self, partner: str, reason: str) -> dict:
        cfg = self.config.get(partner, {})
        beh = FALLBACK_BEHAVIOUR.get(partner, {"queue": False, "data": {}})
        return {
            "message": cfg.get("message", f"{partner.capitalize()} service is temporarily unavailable."),
            "configured_status": cfg.get("status", "TEMPORARILY_UNAVAILABLE"),
            "queue_for_sync": beh["queue"],
            "data": dict(beh["data"]),
            "reason": reason,
        }
