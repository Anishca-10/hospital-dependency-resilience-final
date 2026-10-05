"""Background active health probing (live app only)."""
import threading
import time

from src.partners.partner_simulator import PARTNERS


class HealthMonitor(threading.Thread):
    def __init__(self, hospital, interval_seconds=15):
        super().__init__(daemon=True, name="health-monitor")
        self.hospital = hospital
        self.interval = max(2, float(interval_seconds))
        self._stop_evt = threading.Event()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            for p in PARTNERS:
                try:
                    self.hospital.probe(p)
                except Exception:   # monitoring must never crash the app
                    pass

    def stop(self):
        self._stop_evt.set()
