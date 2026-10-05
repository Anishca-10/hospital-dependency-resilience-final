"""Recorders persist every partner request, every retry attempt and every circuit transition.

MemoryRecorder - used by experiments / unit tests (keeps full detail incl. numeric times).
DBRecorder     - used by the live application (SQLite tables service_calls, retry_attempts, circuit_events).
Only operational metadata is stored - never patient names or clinical content.
"""
import threading


def _call_row(result: dict, source: str, t_start=None, t_end=None) -> dict:
    return {
        "request_id": result["request_id"], "timestamp": result["timestamp"], "partner": result["partner"],
        "operation": result["operation"], "latency_ms": result["latency_ms"], "success": int(result["success"]),
        "status": result["status"], "error_type": result["error_type"], "retry_count": result["retry_count"],
        "circuit_state": result["circuit_state"], "fallback_used": int(result["fallback_used"]),
        "mode": result["mode"], "core_ok": int(result["core_ok"]), "status_code": result["status_code"],
        "source": source, "t_start": t_start, "t_end": t_end,
    }


class MemoryRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._calls, self._attempts, self._events = [], [], []

    def record_call(self, result, source="live", t_start=None, t_end=None):
        with self._lock:
            self._calls.append(_call_row(result, source, t_start, t_end))
            for a in result.get("attempts", []):
                self._attempts.append({"request_id": result["request_id"], "timestamp": result["timestamp"],
                                       "partner": result["partner"], "attempt": a["attempt"],
                                       "result": a["result"], "error_type": None if a["result"] == "SUCCESS" else a["result"],
                                       "status_code": a["status_code"], "latency_ms": a["latency_ms"],
                                       "outcome": a.get("outcome"), "mode": result["mode"], "source": source})

    def record_circuit_event(self, partner, old, new, reason, timestamp, t=None, source="live"):
        with self._lock:
            self._events.append({"timestamp": timestamp, "partner": partner, "old_state": old,
                                 "new_state": new, "reason": reason, "source": source, "t": t})

    def calls(self, source=None, partner=None, limit=None, include_probes=False):
        with self._lock:
            rows = [r for r in self._calls
                    if (source is None or r["source"] == source) and (partner is None or r["partner"] == partner)
                    and (include_probes or r["operation"] != "health_check")]
        return rows[-limit:] if limit else list(rows)

    def recent_calls(self, partner, limit=10, since_iso=None):
        with self._lock:
            rows = [r for r in self._calls if r["partner"] == partner and r["source"] != "experiment"
                    and (since_iso is None or r["timestamp"] >= since_iso)]
        return rows[-limit:]

    def attempts(self, source=None, request_id=None):
        with self._lock:
            return [a for a in self._attempts if (source is None or a["source"] == source)
                    and (request_id is None or a["request_id"] == request_id)]

    def circuit_events(self, source=None):
        with self._lock:
            return [e for e in self._events if source is None or e["source"] == source]

    def clear(self):
        with self._lock:
            self._calls.clear(); self._attempts.clear(); self._events.clear()


class DBRecorder:
    def __init__(self, db):
        self.db = db

    def record_call(self, result, source="live", t_start=None, t_end=None):
        r = _call_row(result, source)
        self.db.execute(
            "INSERT INTO service_calls(request_id,timestamp,partner,operation,latency_ms,success,status,error_type,"
            "retry_count,circuit_state,fallback_used,mode,core_ok,status_code,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["request_id"], r["timestamp"], r["partner"], r["operation"], r["latency_ms"], r["success"], r["status"],
             r["error_type"], r["retry_count"], r["circuit_state"], r["fallback_used"], r["mode"], r["core_ok"],
             r["status_code"], source))
        if result.get("attempts"):
            self.db.executemany(
                "INSERT INTO retry_attempts(request_id,timestamp,partner,attempt,result,error_type,status_code,latency_ms,source) VALUES (?,?,?,?,?,?,?,?,?)",
                [(result["request_id"], result["timestamp"], result["partner"], a["attempt"], a["result"],
                  None if a["result"] == "SUCCESS" else a["result"], a["status_code"], a["latency_ms"], source)
                 for a in result["attempts"]])

    def record_circuit_event(self, partner, old, new, reason, timestamp, t=None, source="live"):
        self.db.execute("INSERT INTO circuit_events(timestamp,partner,old_state,new_state,reason,source) VALUES (?,?,?,?,?,?)",
                        (timestamp, partner, old, new, reason, source))

    def calls(self, source=None, partner=None, limit=None, include_probes=False):
        sql, args = "SELECT * FROM service_calls WHERE 1=1", []
        if source:
            sql += " AND source=?"; args.append(source)
        if partner:
            sql += " AND partner=?"; args.append(partner)
        if not include_probes:
            sql += " AND operation!='health_check'"
        sql += " ORDER BY id DESC" + (f" LIMIT {int(limit)}" if limit else "")
        return list(reversed(self.db.query(sql, args)))

    def recent_calls(self, partner, limit=10, since_iso=None):
        sql, args = "SELECT * FROM service_calls WHERE partner=? AND source!='experiment'", [partner]
        if since_iso:
            sql += " AND timestamp>=?"; args.append(since_iso)
        sql += f" ORDER BY id DESC LIMIT {int(limit)}"
        return list(reversed(self.db.query(sql, args)))

    def attempts(self, source=None, request_id=None):
        sql, args = "SELECT * FROM retry_attempts WHERE 1=1", []
        if source:
            sql += " AND source=?"; args.append(source)
        if request_id:
            sql += " AND request_id=?"; args.append(request_id)
        return self.db.query(sql + " ORDER BY id", args)

    def circuit_events(self, source=None):
        if source:
            return self.db.query("SELECT * FROM circuit_events WHERE source=? ORDER BY id", (source,))
        return self.db.query("SELECT * FROM circuit_events ORDER BY id")
