import os
import time
import random
import pandas as pd
from datetime import datetime, timedelta

def generate_synthetic_data(num_samples: int = 500, output_path: str = "data/generated/synthetic_experiment_data.csv") -> pd.DataFrame:
    """
    Generates synthetic experiment log dataset covering multiple failure scenarios
    for both Baseline and Resilient systems.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    scenarios = [
        "CASE 1: High Latency Lab",
        "CASE 2: Pharmacy Repeated Failures",
        "CASE 3: Insurance Unavailable",
        "CASE 4: Telemedicine Timeout",
        "CASE 5: Multi-Partner Failure Cascade"
    ]
    
    partners = ["Laboratory", "Pharmacy", "Insurance", "Telemedicine"]
    modes = ["baseline", "resilient"]
    
    rows = []
    base_time = datetime.now() - timedelta(hours=2)

    for i in range(num_samples):
        timestamp = (base_time + timedelta(seconds=i * 5)).strftime("%Y-%m-%d %H:%M:%S")
        request_id = f"REQ-{10000 + i}"
        scenario = random.choice(scenarios)
        partner = random.choice(partners)
        mode = random.choice(modes)

        # Baseline logic
        if mode == "baseline":
            if "High Latency" in scenario and partner == "Laboratory":
                latency_ms = random.uniform(3500, 5000)
                status_code = 200
                success = True
                timeout = True
                retry_count = 0
                circuit_state = "DISABLED"
                fallback_used = False
                core_success = False  # Hanging request causes core timeout
                error_type = "LATENCY_TIMEOUT"
            elif "Repeated Failures" in scenario and partner == "Pharmacy":
                latency_ms = random.uniform(100, 250)
                status_code = 500
                success = False
                timeout = False
                retry_count = 0
                circuit_state = "DISABLED"
                fallback_used = False
                core_success = False  # 500 crashes core workflow
                error_type = "HTTP_500_INTERNAL_ERROR"
            elif "Unavailable" in scenario and partner == "Insurance":
                latency_ms = random.uniform(50, 150)
                status_code = 503
                success = False
                timeout = False
                retry_count = 0
                circuit_state = "DISABLED"
                fallback_used = False
                core_success = False  # Core app fails
                error_type = "HTTP_503_SERVICE_UNAVAILABLE"
            else:
                latency_ms = random.uniform(80, 250)
                status_code = 200
                success = True
                timeout = False
                retry_count = 0
                circuit_state = "DISABLED"
                fallback_used = False
                core_success = True
                error_type = "NONE"

        # Resilient logic
        else:
            if "High Latency" in scenario and partner == "Laboratory":
                latency_ms = random.uniform(2000, 2500) # Capped by timeout
                status_code = 200
                success = False
                timeout = True
                retry_count = 2
                circuit_state = "OPEN" if i % 4 == 0 else "CLOSED"
                fallback_used = True
                core_success = True  # Fallback keeps core active!
                error_type = "TIMEOUT_FALLBACK"
            elif "Repeated Failures" in scenario and partner == "Pharmacy":
                latency_ms = random.uniform(50, 120)
                status_code = 500
                success = False
                timeout = False
                retry_count = 2
                circuit_state = "OPEN"
                fallback_used = True
                core_success = True  # Queued prescription
                error_type = "CIRCUIT_OPEN_FALLBACK"
            elif "Unavailable" in scenario and partner == "Insurance":
                latency_ms = random.uniform(20, 80)
                status_code = 503
                success = False
                timeout = False
                retry_count = 0
                circuit_state = "OPEN"
                fallback_used = True
                core_success = True  # Provisional eligibility
                error_type = "PROVISIONAL_FALLBACK"
            else:
                latency_ms = random.uniform(80, 220)
                status_code = 200
                success = True
                timeout = False
                retry_count = 0
                circuit_state = "CLOSED"
                fallback_used = False
                core_success = True
                error_type = "NONE"

        rows.append({
            "timestamp": timestamp,
            "request_id": request_id,
            "scenario": scenario,
            "partner_service": partner,
            "mode": mode,
            "latency_ms": round(latency_ms, 2),
            "status_code": status_code,
            "partner_success": success,
            "timeout": timeout,
            "retry_count": retry_count,
            "circuit_state": circuit_state,
            "fallback_used": fallback_used,
            "core_request_success": core_success,
            "error_type": error_type
        })

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    print(f"[DATA GENERATOR] Saved {len(df)} synthetic experiment records to {output_path}")
    return df

if __name__ == "__main__":
    generate_synthetic_data()
