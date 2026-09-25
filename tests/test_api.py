from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from perry.app import create_app

EVENT = {
    "event_id": "demo-001",
    "source": "synthetic",
    "node": "demo-web-1",
    "cpu_samples_percent": [94, 95, 96, 97, 96, 98],
    "sample_interval_seconds": 60,
    "http_error_percent": 8,
    "maintenance": False,
}


@dataclass
class FakeModel:
    answer: str = "alert"
    confidence: float = 1.0
    version: str = "jev-1.13-free"
    failure: bool = False
    calls: int = 0

    async def decide(self, state: dict) -> dict:
        self.calls += 1
        if self.failure:
            raise TimeoutError("private network details should not be returned")
        return {
            "model": self.version,
            "answers": {
                "alert_decision": {
                    "type": "choice",
                    "choice": self.answer,
                    "probabilities": {"alert": 0.8, "ignore": 0.2},
                    "confidence": self.confidence,
                }
            },
        }


class FakeNotifier:
    def __init__(self, fail: bool = False):
        self.messages = []
        self.fail = fail

    async def send(self, title: str, body: str) -> None:
        self.messages.append((title, body))
        if self.fail:
            raise TimeoutError("private service detail")


@pytest.fixture
def harness(tmp_path):
    model, notifier = FakeModel(), FakeNotifier()
    client = TestClient(
        create_app(db_path=tmp_path / "events.sqlite", model=model, notifier=notifier)
    )
    return client, model, notifier


def test_short_spike_never_calls_model_or_notifier(harness):
    client, model, notifier = harness
    event = {**EVENT, "cpu_samples_percent": [99]}
    result = client.post("/events", json=event)
    assert result.status_code == 200
    assert result.json()["reason"] == "below_hard_rules"
    assert model.calls == 0
    assert notifier.messages == []


def test_same_event_id_is_not_delivered_twice(harness):
    client, model, notifier = harness
    first = client.post("/events", json=EVENT)
    again = client.post("/events", json=EVENT)
    assert first.json() == again.json()
    assert model.calls == 1
    assert len(notifier.messages) == 1


def test_reusing_event_id_for_different_telemetry_is_rejected(harness):
    client, model, notifier = harness
    client.post("/events", json=EVENT)
    response = client.post("/events", json={**EVENT, "http_error_percent": 10})
    assert response.status_code == 409
    assert model.calls == 1
    assert len(notifier.messages) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"failure": True},
        {"version": "jev-unexpected"},
        {"answer": "something-else"},
        {"confidence": 0.2},
    ],
)
def test_model_failure_or_uncertainty_fails_closed(harness, change):
    client, model, notifier = harness
    for key, value in change.items():
        setattr(model, key, value)
    response = client.post("/events", json=EVENT)
    assert response.status_code == 200
    assert response.json()["status"] == "held"
    assert notifier.messages == []
    assert "private" not in str(response.json())
    assert client.get("/decisions/demo-001").json()["status"] == "held"


def test_rejected_notification_is_visible_but_not_claimed_delivered(tmp_path):
    client = TestClient(
        create_app(
            db_path=tmp_path / "events.sqlite", model=FakeModel(), notifier=FakeNotifier(fail=True)
        )
    )
    result = client.post("/events", json=EVENT)
    assert result.json()["status"] == "delivery_failed"
    assert client.get("/decisions/demo-001").json()["reason"] == "notifier_unavailable"


def test_only_synthetic_validated_events_are_accepted(harness):
    client, model, notifier = harness
    result = client.post("/events", json={**EVENT, "source": "mimir"})
    assert result.status_code == 422
    assert model.calls == 0
    assert notifier.messages == []


def test_extra_telemetry_cannot_be_hidden_in_a_synthetic_event(harness):
    client, model, notifier = harness
    response = client.post("/events", json={**EVENT, "raw_metrics": {"private": "data"}})
    assert response.status_code == 422
    assert "private" not in response.text
    assert model.calls == 0
    assert notifier.messages == []


def test_environment_style_allowlist_prevents_unapproved_phone_alerts(tmp_path):
    model, notifier = FakeModel(), FakeNotifier()
    client = TestClient(
        create_app(
            db_path=tmp_path / "events.sqlite",
            model=model,
            notifier=notifier,
            allowed_event_id="approved-test",
        )
    )
    result = client.post("/events", json=EVENT)
    assert result.json()["status"] == "held"
    assert result.json()["reason"] == "notification_not_authorized"
    assert model.calls == 0
    assert notifier.messages == []


def test_staging_event_prefix_allows_new_synthetic_checks_but_holds_other_ids(tmp_path):
    model, notifier = FakeModel(), FakeNotifier()
    client = TestClient(
        create_app(
            db_path=tmp_path / "staging.sqlite",
            model=model,
            notifier=notifier,
            allowed_event_prefix="stage-",
        )
    )
    assert (
        client.post("/events", json={**EVENT, "event_id": "stage-demo-1"}).json()["status"]
        == "alert"
    )
    assert client.post("/events", json={**EVENT, "event_id": "demo-002"}).json()["status"] == "held"
    assert model.calls == 1
    assert len(notifier.messages) == 1


def test_staging_prefix_cannot_be_configured_with_real_apprise(monkeypatch):
    from perry.app import from_environment

    monkeypatch.setenv("PERRY_STAGE_EVENT_PREFIX", "stage-")
    monkeypatch.setenv("PERRY_APPRISE_URL", "http://apprise.apprise.svc/notify/global")
    with pytest.raises(ValueError, match="loopback fake sink"):
        from_environment()


def test_health_metrics_and_missing_decision(harness):
    client, _, _ = harness
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/decisions/unknown").status_code == 404
    client.post("/events", json=EVENT)
    assert "perry_decisions_total" in client.get("/metrics").text
