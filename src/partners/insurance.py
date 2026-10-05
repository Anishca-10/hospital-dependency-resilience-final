"""Insurance partner: response builder (synthetic data only; no real coverage decisions)."""
PARTNER = "insurance"
OPERATIONS = {"verify_eligibility": "Verify insurance eligibility", "health_check": "Health check"}


def build_response(operation: str, payload: dict, rng) -> dict:
    return {
        "synthetic": True,
        "verification_id": f"INS-{rng.randint(100000, 999999)}",
        "patient_id": payload.get("patient_id"),
        "provider": payload.get("provider", "Synthetic Insurer"),
        "eligibility_status": "VERIFIED_SIMULATED",
    }
