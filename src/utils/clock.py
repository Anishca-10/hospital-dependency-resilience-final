"""Clock abstraction.

RealClock is used by the live application (real sleeping, real time).
VirtualClock is used by experiments and unit tests: ``sleep()`` advances a
simulated time counter instantly, so a 5-second partner latency or a 10-second
circuit recovery timeout can be exercised without waiting. All resilience
logic (timeouts, back-off, circuit recovery) reads time ONLY through the clock,
so the same code path runs in both modes.
"""
import datetime as dt
import threading
import time


class RealClock:
    virtual = False

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def now_iso(self) -> str:
        return dt.datetime.now().isoformat(timespec="milliseconds")

    def iso_ago(self, seconds: float) -> str:
        return (dt.datetime.now() - dt.timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


class VirtualClock:
    virtual = True

    def __init__(self, start: float = 1000.0, epoch: dt.datetime = None):
        self._t = float(start)
        self._lock = threading.Lock()
        self._epoch = epoch or dt.datetime(2026, 1, 1, 8, 0, 0)
        self._start = float(start)

    def time(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            with self._lock:
                self._t += seconds

    def advance_to(self, t: float) -> None:
        with self._lock:
            if t > self._t:
                self._t = t

    def now_iso(self) -> str:
        return (self._epoch + dt.timedelta(seconds=self._t - self._start)).isoformat(timespec="milliseconds")

    def iso_ago(self, seconds: float) -> str:
        return (self._epoch + dt.timedelta(seconds=self._t - self._start - seconds)).isoformat(timespec="milliseconds")
