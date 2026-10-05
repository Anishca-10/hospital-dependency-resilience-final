"""Laboratory partner: response builder (synthetic data only)."""
PARTNER = "laboratory"
OPERATIONS = {"order_test": "Order laboratory test", "health_check": "Health check"}


def build_response(operation: str, payload: dict, rng) -> dict:
    return {
        "synthetic": True,
        "lab_order_id": f"LAB-{rng.randint(10000, 99999)}",
        "patient_id": payload.get("patient_id"),
        "test_type": payload.get("test_type", "Complete Blood Count (CBC)"),
        "order_status": "ORDER_ACCEPTED",
    }
