"""Prototype / simulated user-validation questionnaire and summary generator.

IMPORTANT: this is a PROTOTYPE validation instrument. It is not a clinical study and
no hospital stakeholder interviews are claimed. Only responses actually submitted
through the application are summarised.
"""
import datetime as dt

QUESTIONS = [
    {"id": "q1", "type": "likert", "text": "Is dependency status understandable?"},
    {"id": "q2", "type": "likert", "text": "Are failure messages clear?"},
    {"id": "q3", "type": "likert", "text": "Is the dashboard useful?"},
    {"id": "q4", "type": "likert", "text": "Does fallback behavior make sense?"},
    {"id": "q5", "type": "likert", "text": "Is the simulation useful?"},
    {"id": "q6", "type": "likert", "text": "Would the system improve operational awareness?"},
    {"id": "q7", "type": "text", "text": "What should be improved?"},
]
Q_TEXT = {q["id"]: q["text"] for q in QUESTIONS}
DISCLAIMER = ("Prototype/simulated user validation: responses come from people trying this prototype with "
              "synthetic data. It is not a clinical evaluation and does not represent hospital stakeholder interviews.")


def save_submission(db, role, answers: dict, ts: str):
    """answers: {"q1": 1..5, ..., "q7": "free text"}. Returns number of rows stored."""
    n = 0
    for q in QUESTIONS:
        val = answers.get(q["id"])
        if q["type"] == "likert":
            if val in (None, ""):
                continue
            rating = int(val)
            if not 1 <= rating <= 5:
                raise ValueError(f"{q['id']} rating must be between 1 and 5")
            db.execute("INSERT INTO user_feedback(timestamp,role,rating,question,response) VALUES (?,?,?,?,?)",
                       (ts, role, rating, q["text"], str(answers.get(q["id"] + "_comment", "") or "")))
            n += 1
        elif val and str(val).strip():
            db.execute("INSERT INTO user_feedback(timestamp,role,rating,question,response) VALUES (?,?,?,?,?)",
                       (ts, role, None, q["text"], str(val).strip()[:1000]))
            n += 1
    if n == 0:
        raise ValueError("No answers supplied")
    return n


def summarize(db):
    rows = db.query("SELECT * FROM user_feedback ORDER BY id")
    roles = sorted({r["role"] for r in rows})
    out = {"total_rows": len(rows), "roles": {}, "likert_questions": [q["text"] for q in QUESTIONS if q["type"] == "likert"]}
    for role in roles:
        rr = [r for r in rows if r["role"] == role]
        per_q = {}
        for q in QUESTIONS:
            if q["type"] == "likert":
                vals = [r["rating"] for r in rr if r["question"] == q["text"] and r["rating"] is not None]
                per_q[q["text"]] = {"n": len(vals), "mean": round(sum(vals) / len(vals), 2) if vals else None}
        comments = [r["response"] for r in rr if r["question"] == Q_TEXT["q7"] and r["response"]]
        submissions = len({r["timestamp"] for r in rr})
        out["roles"][role] = {"submissions": submissions, "questions": per_q, "improvement_comments": comments}
    return out


def render_summary_md(db) -> str:
    s = summarize(db)
    lines = ["# User Feedback Summary", "", f"> **{DISCLAIMER}**", "",
             f"_Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from the `user_feedback` table (SQLite). "
             "Nothing in this file is hand-written or invented._", ""]
    if not s["roles"]:
        lines += ["**No responses have been collected yet.**", "",
                  "To collect them: start the app, log in as `manager` or `clinician`, open *User Validation*, "
                  "complete the questionnaire after trying the failure simulation, then re-generate this file "
                  "(`python scripts/generate_feedback_summary.py` or the *Regenerate summary* button).", "",
                  "## Questionnaire", ""]
        lines += [f"{i}. {q['text']} ({'1-5 rating' if q['type'] == 'likert' else 'free text'})"
                  for i, q in enumerate(QUESTIONS, 1)]
        return "\n".join(lines) + "\n"
    lines += ["## Mean ratings (1 = strongly disagree, 5 = strongly agree)", "",
              "| Question | " + " | ".join(f"{r} (n)" for r in s["roles"]) + " |",
              "|---|" + "---|" * len(s["roles"])]
    for q in s["likert_questions"]:
        cells = []
        for role in s["roles"]:
            d = s["roles"][role]["questions"][q]
            cells.append(f"{d['mean']} ({d['n']})" if d["mean"] is not None else "-")
        lines.append(f"| {q} | " + " | ".join(cells) + " |")
    lines += ["", "## Submissions per role", ""]
    lines += [f"- {role}: {d['submissions']}" for role, d in s["roles"].items()]
    lines += ["", "## What should be improved? (verbatim responses)", ""]
    any_c = False
    for role, d in s["roles"].items():
        for c in d["improvement_comments"]:
            lines.append(f"- **{role}**: {c}")
            any_c = True
    if not any_c:
        lines.append("_No free-text responses._")
    lines += ["", "Small sample sizes mean these numbers are indicative only."]
    return "\n".join(lines) + "\n"
