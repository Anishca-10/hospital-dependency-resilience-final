"""Regenerate docs/user_feedback_summary.md from the user_feedback table."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from src.database.db import Database
from src.utils import validation_survey as survey

db = Database(os.path.join(ROOT, "data", "hospital_resilience.db"))
with open(os.path.join(ROOT, "docs", "user_feedback_summary.md"), "w", encoding="utf-8") as fh:
    fh.write(survey.render_summary_md(db))
print("docs/user_feedback_summary.md regenerated")
