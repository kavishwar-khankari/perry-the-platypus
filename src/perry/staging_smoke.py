"""Runs inside a GitOps-managed staging Job, not on a public CI runner."""

import json
import os
import time
import urllib.error
import urllib.request
import uuid


def request(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def wait_until_ready(base: str, sink: str) -> None:
    for _ in range(60):
        try:
            if request(f"{base}/healthz") == {"status": "ok"} and "count" in request(
                f"{sink}/calls"
            ):
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(5)
    raise AssertionError("Staging service or fake sink is not ready")


def main() -> None:
    base = os.environ["PERRY_STAGE_URL"].rstrip("/")
    sink = os.environ["PERRY_STAGE_SINK_URL"].rstrip("/")
    event_id = os.getenv("PERRY_STAGE_EVENT_ID") or (
        os.environ["PERRY_STAGE_EVENT_PREFIX"] + uuid.uuid4().hex
    )
    wait_until_ready(base, sink)
    initial_count = request(f"{sink}/calls")["count"]
    event = {
        "event_id": event_id,
        "source": "synthetic",
        "node": "demo-staging-node",
        "cpu_samples_percent": [94, 95, 96, 97, 96, 98],
        "sample_interval_seconds": 60,
        "http_error_percent": 8,
        "maintenance": False,
    }
    positive = request(f"{base}/events", event)
    if positive["status"] != "alert" or positive["choice"] != "alert":
        raise AssertionError(
            "Staging recorded no alert: "
            f"status={positive['status']} reason={positive['reason']} "
            f"choice={positive['choice']}"
        )
    if request(f"{base}/decisions/{event_id}")["status"] != "alert":
        raise AssertionError("Staging decision was not persisted")
    after_positive = request(f"{sink}/calls")["count"]
    if after_positive != initial_count + 1:
        raise AssertionError("Staging sink did not receive exactly one new alert")
    negative = request(
        f"{base}/events", {**event, "event_id": f"{event_id}-maint", "maintenance": True}
    )
    if negative["status"] != "suppressed" or negative["reason"] != "maintenance":
        raise AssertionError(
            f"Maintenance was not suppressed correctly: {negative['status']}/{negative['reason']}"
        )
    if request(f"{sink}/calls")["count"] != after_positive:
        raise AssertionError("Maintenance reached the notification sink")
    print("Staging smoke passed: real Jev Choice, stored decision, fake sink, no-alert.")


if __name__ == "__main__":
    main()
