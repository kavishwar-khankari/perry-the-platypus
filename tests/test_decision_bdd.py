from dataclasses import dataclass, field

from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

from perry.app import create_app

scenarios("features/decision.feature")


@dataclass
class FakeJev:
    choice: str = "alert"
    calls: int = 0

    async def decide(self, state: dict) -> dict:
        self.calls += 1
        return {
            "model": "jev-1.13-free",
            "answers": {
                "alert_decision": {
                    "type": "choice",
                    "choice": self.choice,
                    "probabilities": {
                        "alert": 1.0 if self.choice == "alert" else 0.0,
                        "ignore": 0.0 if self.choice == "alert" else 1.0,
                    },
                    "confidence": 1.0,
                }
            },
        }


@dataclass
class FakeApprise:
    messages: list[dict] = field(default_factory=list)

    async def send(self, title: str, body: str) -> None:
        self.messages.append({"title": title, "body": body})


@given(
    "synthetic CPU is high for six minutes and service errors are elevated", target_fixture="event"
)
def high_cpu_event():
    return high_cpu_fixture()


def high_cpu_fixture():
    return {
        "event_id": "demo-001",
        "source": "synthetic",
        "node": "demo-web-1",
        "cpu_samples_percent": [94, 95, 96, 97, 96, 98],
        "sample_interval_seconds": 60,
        "http_error_percent": 8,
        "maintenance": False,
    }


@given("a sustained synthetic problem during maintenance", target_fixture="event")
def maintenance_event():
    return {**high_cpu_fixture(), "event_id": "demo-002", "maintenance": True}


@given("Jev chooses alert", target_fixture="jev")
def jev_alert():
    return FakeJev(choice="alert")


@when("Perry processes the event", target_fixture="result")
def process_event(event, jev, tmp_path):
    apprise = FakeApprise()
    client = TestClient(
        create_app(db_path=tmp_path / "decisions.sqlite", model=jev, notifier=apprise)
    )
    response = client.post("/events", json=event)
    assert response.status_code == 200
    saved = client.get(f"/decisions/{event['event_id']}")
    assert saved.status_code == 200
    return {"posted": response.json(), "saved": saved.json(), "apprise": apprise, "jev": jev}


@then("the recorded decision is alert")
def is_alert(result):
    assert result["posted"]["status"] == "alert"
    assert result["saved"]["status"] == "alert"


@then("the recorded decision is suppressed")
def is_suppressed(result):
    assert result["posted"]["status"] == "suppressed"
    assert result["saved"]["status"] == "suppressed"
    assert result["jev"].calls == 0


@then("the notification receiver is called once")
def called_once(result):
    assert len(result["apprise"].messages) == 1
    assert result["apprise"].messages[0]["title"].startswith("[PERRY POC — SYNTHETIC]")


@then("the notification receiver is never called")
def never_called(result):
    assert result["apprise"].messages == []
