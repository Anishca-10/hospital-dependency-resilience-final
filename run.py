"""One-command startup:  python run.py

Initialises directories, the SQLite database, configuration, demo users and synthetic data,
then starts the Flask server (with background partner health probing).
"""
import os
import sys

ROOT = os.path.abspath(os.path.dirname(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402
from src.utils.config_manager import ConfigManager  # noqa: E402


def main():
    for d in ("data", "data/results", "outputs/figures", "outputs/reports", "docs"):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    cfg = ConfigManager(os.path.join(ROOT, "config", "config.yaml"), persist=False).get()
    host = os.environ.get("HOST", cfg["server"]["host"])
    port = int(os.environ.get("PORT", cfg["server"]["port"]))
    app = create_app(start_monitor=True)
    db = app.extensions["db"]
    n_pat = db.query_one("SELECT COUNT(*) AS n FROM patients")["n"]
    print("=" * 40)
    print("Hospital Dependency Resilience Platform")
    print("=" * 40)
    print(f"\nServer:\nhttp://{host}:{port}\n")
    print("Demo users:\n")
    print("Operations Manager:\nmanager / manager123\n")
    print("Clinical Staff:\nclinician / clinician123\n")
    print("Administrator (optional):\nadmin / admin123\n")
    print(f"Database: data/hospital_resilience.db ({n_pat} synthetic patients)")
    print("Synthetic data and simulated partners only - not for production clinical use.")
    print("=" * 40)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
