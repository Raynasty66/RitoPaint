"""
Background poller for the Replay API camera.

Runs on its own thread over a keep-alive Session so painting never blocks on
HTTP, and timestamps every sample so the pose can be extrapolated forward to
the instant the overlay actually paints.
"""
import threading
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REPLAY_API = "https://127.0.0.1:2999/replay"


class CameraFeed:
    def __init__(self, url=REPLAY_API, poll_hz=120.0):
        self.url = url
        self.poll_interval = 1.0 / poll_hz

        self._lock = threading.Lock()
        self._thread = None
        self._running = False

        # two most recent samples, each (timestamp, render_dict)
        self._previous = None
        self._latest = None

        self.connected = False
        self.measured_hz = 0.0
        self.last_error = None

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _loop(self):
        # keep-alive: one TLS handshake for the whole run, not 120 a second
        session = requests.Session()
        session.verify = False

        intervals = []
        while self._running:
            started = time.perf_counter()
            try:
                response = session.get(f"{self.url}/render", timeout=1.0)
                response.raise_for_status()
                render = response.json()
                now = time.perf_counter()

                with self._lock:
                    if self._latest is not None:
                        self._previous = self._latest
                        intervals.append(now - self._latest[0])
                        if len(intervals) > 60:
                            intervals.pop(0)
                        if intervals:
                            self.measured_hz = len(intervals) / sum(intervals)
                    self._latest = (now, render)
                    self.connected = True
                    self.last_error = None
            except requests.exceptions.RequestException as exc:
                with self._lock:
                    self.connected = False
                    self.last_error = str(exc)
                time.sleep(0.25)  # no replay loaded - back off instead of spinning
                continue

            elapsed = time.perf_counter() - started
            if elapsed < self.poll_interval:
                time.sleep(self.poll_interval - elapsed)

    # -- reading -------------------------------------------------------------

    def latest(self):
        """Returns (age_seconds, render_dict) or (None, None) if nothing yet."""
        with self._lock:
            if self._latest is None:
                return None, None
            timestamp, render = self._latest
            return time.perf_counter() - timestamp, render

    def predicted(self, lead_seconds=0.0):
        """
        Extrapolate cameraPosition/cameraRotation from the last two samples to
        (now + lead_seconds). A lead of 0 still corrects for however stale the
        newest sample is. Returns a render dict shaped like the API response,
        or None.
        """
        with self._lock:
            latest = self._latest
            previous = self._previous

        if latest is None:
            return None

        latest_time, latest_render = latest
        target_time = time.perf_counter() + lead_seconds

        if previous is None:
            return latest_render

        previous_time, previous_render = previous
        span = latest_time - previous_time
        if span <= 1e-6:
            return latest_render

        extrapolation_dt = target_time - latest_time
        # a hitch in the poll loop shouldn't fling the camera somewhere silly
        extrapolation_dt = max(-span, min(extrapolation_dt, 4.0 * span))

        predicted = dict(latest_render)
        for key in ("cameraPosition", "cameraRotation"):
            new = latest_render.get(key)
            old = previous_render.get(key)
            if not isinstance(new, dict) or not isinstance(old, dict):
                continue
            out = {}
            for axis in ("x", "y", "z"):
                a = float(old.get(axis, 0.0))
                b = float(new.get(axis, 0.0))
                velocity = (b - a) / span
                out[axis] = b + velocity * extrapolation_dt
            predicted[key] = out

        return predicted
