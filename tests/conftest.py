import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.hospital_service import HospitalCoreService  # noqa: E402
from src.partners.partner_simulator import PartnerSimulator  # noqa: E402
from src.utils.clock import VirtualClock  # noqa: E402
from src.utils.config_manager import ConfigManager  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def quiet_config(**over):
    """Config snapshot with NO background failures so tests are deterministic."""
    cfg = ConfigManager(os.path.join(ROOT, "config", "config.yaml"), persist=False).get()
    for p in cfg["partners"].values():
        p["failure_rate"] = 0.0
    for k, v in over.items():
        cfg[k].update(v) if isinstance(v, dict) else cfg.__setitem__(k, v)
    return cfg


@pytest.fixture
def cfg():
    return quiet_config()


@pytest.fixture
def clock():
    return VirtualClock()


@pytest.fixture
def sim(cfg, clock):
    return PartnerSimulator(cfg, clock, seed=7)


@pytest.fixture
def hospital(cfg, clock):
    return HospitalCoreService(ConfigManager.from_dict(cfg), clock=clock, seed=7, enable_pending_sync=False)


@pytest.fixture
def app_env(tmp_path, cfg, clock):
    """Flask app on a temp DB, temp config copy, virtual clock, quiet partners."""
    import yaml
    from app import create_app
    cpath = tmp_path / "config.yaml"
    cpath.write_text(yaml.safe_dump(cfg))
    app = create_app(config_path=str(cpath), db_path=str(tmp_path / "t.db"), clock=clock, seed=3,
                     results_dir=str(tmp_path / "results"))
    app.config["TESTING"] = True
    return app, clock, cpath


def login(app, user, pw):
    c = app.test_client()
    r = c.post("/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.data
    return c
