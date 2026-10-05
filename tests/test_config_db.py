import os

import pytest
import yaml

from src.database.db import Database
from src.utils.config_manager import ConfigError, ConfigManager

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_config_loads_spec_structure():
    c = ConfigManager(os.path.join(ROOT, "config", "config.yaml"), persist=False).get()
    assert c["resilience"]["timeout"] == {"laboratory": 2.0, "pharmacy": 2.0, "insurance": 3.0, "telemedicine": 2.0}
    assert c["resilience"]["retry"]["max_attempts"] == 2 and c["resilience"]["retry"]["backoff_seconds"] == 0.2
    assert c["resilience"]["circuit_breaker"]["half_open_max_calls"] == 1
    assert c["partners"]["insurance"]["latency_ms"] == 500


@pytest.mark.parametrize("patch,needle", [
    ({"resilience": {"timeout": {"laboratory": 0}}}, "timeout.laboratory"),
    ({"resilience": {"timeout": {"laboratory": -1}}}, "timeout.laboratory"),
    ({"resilience": {"retry": {"max_attempts": 6}}}, "max_attempts"),
    ({"resilience": {"retry": {"max_attempts": -1}}}, "max_attempts"),
    ({"resilience": {"circuit_breaker": {"failure_threshold": 0}}}, "failure_threshold"),
    ({"resilience": {"circuit_breaker": {"failure_threshold": 21}}}, "failure_threshold"),
    ({"partners": {"pharmacy": {"failure_rate": 1.5}}}, "failure_rate"),
    ({"partners": {"pharmacy": {"failure_rate": "abc"}}}, "failure_rate"),
])
def test_config_validation_rejects_bad_values(patch, needle):
    cm = ConfigManager(os.path.join(ROOT, "config", "config.yaml"), persist=False)
    before = cm.get()
    with pytest.raises(ConfigError) as e:
        cm.update(patch)
    assert any(needle in m for m in e.value.errors)
    assert cm.get() == before            # invalid update leaves config untouched


def test_config_accepts_percent_and_persists(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump({"partners": {"insurance": {"failure_rate": 0.1}}}))
    cm = ConfigManager(str(path))
    cm.update({"partners": {"insurance": {"failure_rate": "100%"}}, "resilience": {"retry": {"max_attempts": 4}}})
    again = ConfigManager(str(path)).get()
    assert again["partners"]["insurance"]["failure_rate"] == 1.0 and again["resilience"]["retry"]["max_attempts"] == 4


def test_database_auto_initialises_with_all_tables(tmp_path):
    db = Database(str(tmp_path / "x" / "h.db"))
    cm = ConfigManager(os.path.join(ROOT, "config", "config.yaml"), persist=False)
    db.initialize(cm.get())
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("patients", "appointments", "partners", "service_calls", "failure_events", "experiment_runs",
              "user_feedback", "users", "retry_attempts", "circuit_events", "pending_actions"):
        assert t in tables
    assert db.query_one("SELECT COUNT(*) n FROM patients")["n"] > 0
    assert db.query_one("SELECT COUNT(*) n FROM partners")["n"] == 4
    db.initialize(cm.get())               # idempotent
    assert db.query_one("SELECT COUNT(*) n FROM users")["n"] == 3
    cols = {r["name"] for r in db.query("PRAGMA table_info(service_calls)")}
    assert {"request_id", "timestamp", "partner", "operation", "latency_ms", "success", "status", "error_type",
            "retry_count", "circuit_state", "fallback_used"} <= cols


def test_passwords_are_hashed_and_verified(tmp_path):
    db = Database(str(tmp_path / "h.db"))
    db.seed_demo_users()
    row = db.query_one("SELECT password_hash FROM users WHERE username='manager'")
    assert "manager123" not in row["password_hash"]
    assert db.verify_user("manager", "manager123")["role"] == "operations_manager"
    assert db.verify_user("manager", "wrong") is None and db.verify_user("nobody", "x") is None
