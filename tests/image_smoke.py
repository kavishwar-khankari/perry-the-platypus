"""Black-box check of the exact container image built for this commit."""

import json
import os
import time
import urllib.request

PERRY = os.getenv("PERRY_TEST_BASE", "http://127.0.0.1:18080")
FAKES = "http://127.0.0.1:18081"


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def post(url: str, body: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def main() -> None:
    for _ in range(40):
        try:
            if get(f"{PERRY}/healthz")["status"] == "ok":
                break
        except OSError:
            time.sleep(0.5)
    else:
        raise AssertionError("Built image did not become healthy")

    high_cpu = {
        "event_id": "image-smoke-alert",
        "source": "synthetic",
        "node": "demo-node",
        "cpu_samples_percent": [94, 95, 96, 97, 96, 98],
        "sample_interval_seconds": 60,
        "http_error_percent": 8,
        "maintenance": False,
    }
    assert post(f"{PERRY}/events", high_cpu)["status"] == "alert"
    assert get(f"{PERRY}/decisions/image-smoke-alert")["choice"] == "alert"
    assert (
        post(
            f"{PERRY}/events",
            {**high_cpu, "event_id": "image-smoke-maintenance", "maintenance": True},
        )["status"]
        == "suppressed"
    )
    assert post(f"{PERRY}/events", high_cpu)["status"] == "alert"  # duplicate is read-only
    calls = get(f"{FAKES}/calls")
    assert calls["jev"] == 1
    assert len(calls["apprise"]) == 1
    assert calls["apprise"][0]["title"].startswith("[PERRY POC — SYNTHETIC]")
    print("Built-image smoke: alert, no-alert, record, and idempotency passed (fakes only).")


if __name__ == "__main__":
    main()
