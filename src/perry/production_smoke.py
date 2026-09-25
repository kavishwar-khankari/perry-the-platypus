"""Runs inside the production PostSync Job; never sends the approved notification."""

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


def wait_until_healthy(base: str) -> None:
    for _ in range(60):
        try:
            if request(f"{base}/healthz") == {"status": "ok"}:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(5)
    raise AssertionError("Production service is not healthy")


def main() -> None:
    base = os.environ["PERRY_PROD_URL"].rstrip("/")
    approved = os.environ["PERRY_APPROVED_EVENT_ID"]
    wait_until_healthy(base)
    event = {
        "event_id": f"prod-smoke-{uuid.uuid4().hex}",
        "source": "synthetic",
        "node": "demo-prod-node",
        "cpu_samples_percent": [94, 95, 96, 97, 96, 98],
        "sample_interval_seconds": 60,
        "http_error_percent": 8,
        "maintenance": False,
    }
    if event["event_id"] == approved:
        raise AssertionError("Smoke event must never reuse the approved phone-test ID")
    held = request(f"{base}/events", event)
    if held["status"] != "held" or held["reason"] != "notification_not_authorized":
        raise AssertionError(f"Unauthorized event was not held: {held['status']}/{held['reason']}")
    suppressed = request(
        f"{base}/events",
        {**event, "event_id": f"{event['event_id']}-maint", "maintenance": True},
    )
    if suppressed["status"] != "suppressed" or suppressed["reason"] != "maintenance":
        raise AssertionError(
            f"Maintenance event was not suppressed: {suppressed['status']}/{suppressed['reason']}"
        )
    print(
        "Production smoke passed: healthy, unauthorized held, maintenance suppressed, "
        "no notification sent."
    )


if __name__ == "__main__":
    main()
