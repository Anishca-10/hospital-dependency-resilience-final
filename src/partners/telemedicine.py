"""Telemedicine partner: response builder (synthetic data only)."""
PARTNER = "telemedicine"
OPERATIONS = {"book_consult": "Book telemedicine consultation", "health_check": "Health check"}


def build_response(operation: str, payload: dict, rng) -> dict:
    return {
        "synthetic": True,
        "consultation_id": f"TELE-{rng.randint(10000, 99999)}",
        "patient_id": payload.get("patient_id"),
        "slot": payload.get("slot", "next available (simulated)"),
        "booking_status": "BOOKED_SIMULATED",
    }
