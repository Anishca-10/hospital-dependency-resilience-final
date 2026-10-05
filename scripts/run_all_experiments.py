"""One command:  python scripts/run_all_experiments.py

1. (re)generate synthetic data / database, 2. run BASELINE, 3. run RESILIENT, 4. compare,
5. compute metrics, 6. generate charts, 7. generate the experiment report.
"""
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from experiments.runner import run_suite  # noqa: E402
from src.database.db import Database  # noqa: E402
from src.utils.config_manager import ConfigManager  # noqa: E402


def main():
    print("=" * 72)
    print("Hospital Dependency Resilience Platform - experiment suite")
    print("=" * 72)
    cm = ConfigManager("config/config.yaml", persist=False)
    print("[1/7] Initialising database and synthetic data ...")
    db = Database("data/hospital_resilience.db")
    db.initialize(cm.get())
    print("[2-7] Running baseline + resilient scenarios, comparing, charting, reporting ...\n")
    t = time.time()
    s = run_suite(cm, db=db, results_dir="data/results", figures_dir="outputs/figures", reports_dir="docs", verbose=True)
    print("\nGenerating documents from measured results ...")
    import generate_docs
    generate_docs.main()
    print(f"\nDone in {time.time() - t:.1f}s")
    print("  CSVs    : data/results/{baseline,resilient,comparison}_results.csv")
    print("  Charts  : outputs/figures/*.png")
    print("  Report  : docs/experiment_report.md")
    return s


if __name__ == "__main__":
    main()
