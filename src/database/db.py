"""SQLite persistence. The database is created automatically on first start."""
import os
import random
import sqlite3
import threading
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    full_name TEXT
);
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT UNIQUE NOT NULL,
    patient_name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    department TEXT,
    registration_date TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id TEXT UNIQUE NOT NULL,
    patient_id TEXT NOT NULL,
    doctor TEXT,
    appointment_date TEXT,
    appointment_type TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS partners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_name TEXT UNIQUE NOT NULL,
    service_type TEXT,
    status TEXT,
    latency_ms REAL,
    error_rate REAL,
    circuit_state TEXT,
    last_failure TEXT,
    last_recovery TEXT
);
CREATE TABLE IF NOT EXISTS service_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    timestamp TEXT,
    partner TEXT,
    operation TEXT,
    latency_ms REAL,
    success INTEGER,
    status TEXT,
    error_type TEXT,
    retry_count INTEGER,
    circuit_state TEXT,
    fallback_used INTEGER,
    mode TEXT,
    core_ok INTEGER,
    status_code INTEGER,
    source TEXT DEFAULT 'live'
);
CREATE TABLE IF NOT EXISTS retry_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    timestamp TEXT,
    partner TEXT,
    attempt INTEGER,
    result TEXT,
    error_type TEXT,
    status_code INTEGER,
    latency_ms REAL,
    source TEXT DEFAULT 'live'
);
CREATE TABLE IF NOT EXISTS circuit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    partner TEXT,
    old_state TEXT,
    new_state TEXT,
    reason TEXT,
    source TEXT DEFAULT 'live'
);
CREATE TABLE IF NOT EXISTS failure_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    partner TEXT,
    failure_type TEXT,
    severity TEXT,
    description TEXT,
    resolved INTEGER DEFAULT 0,
    recovery_time REAL
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    timestamp TEXT,
    partner TEXT,
    operation TEXT,
    patient_id TEXT,
    status TEXT DEFAULT 'PENDING',
    synced_at TEXT
);
CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    timestamp TEXT,
    mode TEXT,
    scenario TEXT,
    total_requests INTEGER,
    successful_requests INTEGER,
    failed_requests INTEGER,
    availability REAL,
    average_latency REAL,
    p95_latency REAL,
    retry_count INTEGER,
    fallback_count INTEGER,
    circuit_open_count INTEGER,
    recovery_time REAL
);
CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    role TEXT,
    rating INTEGER,
    question TEXT,
    response TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_partner ON service_calls(partner, id);
CREATE INDEX IF NOT EXISTS idx_attempts_req ON retry_attempts(request_id);
"""

DEMO_USERS = [
    ("manager", "manager123", "operations_manager", "Operations Manager (demo)"),
    ("clinician", "clinician123", "clinical_staff", "Clinical Staff (demo)"),
    ("admin", "admin123", "admin", "Administrator (demo)"),
]

PARTNER_SERVICE_TYPES = {
    "laboratory": "Laboratory test ordering",
    "pharmacy": "Prescription / medication check",
    "insurance": "Insurance eligibility verification",
    "telemedicine": "Telemedicine scheduling",
}

_FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Arjun", "Nisha", "Vikram", "Anaya",
          "Sanjay", "Priya", "Karthik", "Lakshmi", "Dev", "Tara", "Imran", "Zoya", "Neil", "Sara"]
_LAST = ["Sharma", "Iyer", "Nair", "Reddy", "Patel", "Menon", "Gupta", "Das", "Khan", "Rao"]
_DEPTS = ["General Medicine", "Cardiology", "Orthopaedics", "Paediatrics", "Neurology", "Dermatology"]
_DOCTORS = ["Dr. Synthetic A", "Dr. Synthetic B", "Dr. Synthetic C", "Dr. Synthetic D"]
_APPT_TYPES = ["Consultation", "Follow-up", "Review"]


class Database:
    """Thin SQLite wrapper. One short-lived connection per operation (thread-safe)."""

    def __init__(self, path: str = "data/hospital_resilience.db"):
        self.path = path
        self._write_lock = threading.RLock()
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.init_schema()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def init_schema(self):
        with self._write_lock, self.conn() as c:
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            c.executescript(SCHEMA)

    def execute(self, sql, params=()):
        with self._write_lock, self.conn() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def executemany(self, sql, rows):
        with self._write_lock, self.conn() as c:
            c.executemany(sql, rows)

    def query(self, sql, params=()):
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---------------------------------------------------------------- seeding
    def seed_demo_users(self):
        for username, pw, role, name in DEMO_USERS:
            if not self.query_one("SELECT id FROM users WHERE username=?", (username,)):
                self.execute(
                    "INSERT INTO users(username,password_hash,role,full_name) VALUES (?,?,?,?)",
                    (username, generate_password_hash(pw, method="pbkdf2:sha256"), role, name),
                )

    def seed_synthetic_data(self, n_patients: int = 24, seed: int = 2026):
        """Create SYNTHETIC patients/appointments (no real data) if the tables are empty."""
        if self.query_one("SELECT COUNT(*) AS n FROM patients")["n"] > 0:
            return
        rng = random.Random(seed)
        pats, appts = [], []
        for i in range(n_patients):
            pid = f"P-{1001 + i}"
            name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)} (synthetic)"
            pats.append((pid, name, rng.randint(1, 90), rng.choice(["F", "M"]), rng.choice(_DEPTS),
                         f"2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)}"))
            appts.append((f"A-{5001 + i}", pid, rng.choice(_DOCTORS),
                          f"2026-10-{rng.randint(1, 28):02d} {rng.randint(9, 16):02d}:00",
                          rng.choice(_APPT_TYPES), "SCHEDULED"))
        self.executemany("INSERT INTO patients(patient_id,patient_name,age,gender,department,registration_date) VALUES (?,?,?,?,?,?)", pats)
        self.executemany("INSERT INTO appointments(appointment_id,patient_id,doctor,appointment_date,appointment_type,status) VALUES (?,?,?,?,?,?)", appts)

    def seed_partners(self, config: dict):
        for key, cfg in config["partners"].items():
            if not self.query_one("SELECT id FROM partners WHERE partner_name=?", (key,)):
                self.execute(
                    "INSERT INTO partners(partner_name,service_type,status,latency_ms,error_rate,circuit_state) VALUES (?,?,?,?,?,?)",
                    (key, PARTNER_SERVICE_TYPES.get(key, key), "UNKNOWN", cfg["latency_ms"], cfg["failure_rate"], "CLOSED"),
                )

    def initialize(self, config: dict):
        self.seed_demo_users()
        self.seed_synthetic_data()
        self.seed_partners(config)

    # ------------------------------------------------------------------ users
    def verify_user(self, username: str, password: str):
        row = self.query_one("SELECT * FROM users WHERE username=?", (username,))
        if row and check_password_hash(row["password_hash"], password):
            return {"username": row["username"], "role": row["role"], "full_name": row["full_name"]}
        return None

    # --------------------------------------------------------------- patients
    def list_patients(self):
        return self.query("SELECT * FROM patients ORDER BY id")

    def get_patient(self, patient_id: str):
        return self.query_one("SELECT * FROM patients WHERE patient_id=?", (patient_id,))

    def add_patient(self, name, age, gender, department, today):
        n = self.query_one("SELECT COUNT(*) AS n FROM patients")["n"]
        pid = f"P-{1001 + n}"
        while self.get_patient(pid):
            n += 1
            pid = f"P-{1001 + n}"
        self.execute("INSERT INTO patients(patient_id,patient_name,age,gender,department,registration_date) VALUES (?,?,?,?,?,?)",
                     (pid, name, age, gender, department, today))
        return self.get_patient(pid)

    def list_appointments(self, patient_id=None):
        if patient_id:
            return self.query("SELECT * FROM appointments WHERE patient_id=? ORDER BY appointment_date", (patient_id,))
        return self.query("SELECT * FROM appointments ORDER BY appointment_date")

    def add_appointment(self, patient_id, doctor, date, appt_type):
        n = self.query_one("SELECT COUNT(*) AS n FROM appointments")["n"]
        aid = f"A-{5001 + n}"
        while self.query_one("SELECT 1 FROM appointments WHERE appointment_id=?", (aid,)):
            n += 1
            aid = f"A-{5001 + n}"
        self.execute("INSERT INTO appointments(appointment_id,patient_id,doctor,appointment_date,appointment_type,status) VALUES (?,?,?,?,?,?)",
                     (aid, patient_id, doctor, date, appt_type, "SCHEDULED"))
        return self.query_one("SELECT * FROM appointments WHERE appointment_id=?", (aid,))

    # ------------------------------------------------------------ partner rows
    def update_partner_row(self, partner, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE partners SET {cols} WHERE partner_name=?", (*fields.values(), partner))

    def list_partner_rows(self):
        return self.query("SELECT * FROM partners ORDER BY id")
