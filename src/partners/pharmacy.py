"""Pharmacy partner: response builder (synthetic data only)."""
PARTNER = "pharmacy"
OPERATIONS = {"check_prescription": "Check prescription / medication", "health_check": "Health check"}


def build_response(operation: str, payload: dict, rng) -> dict:
    return {
        "synthetic": True,
        "prescription_id": f"RX-{rng.randint(10000, 99999)}",
        "patient_id": payload.get("patient_id"),
        "medication": payload.get("medication", "Synthetic Medication 500mg"),
        "prescription_status": "ACTIVE_ON_FILE",
    }
