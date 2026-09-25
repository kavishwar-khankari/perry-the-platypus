import pytest

from perry import production_smoke


def test_production_smoke_never_touches_the_approved_phone_event(monkeypatch):
    monkeypatch.setenv("PERRY_PROD_URL", "http://perry.test")
    monkeypatch.setenv("PERRY_APPROVED_EVENT_ID", "perry-phone-test-001")
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _seconds: None)
    submitted = []

    def fake_request(url, body=None):
        if url.endswith("/healthz"):
            return {"status": "ok"}
        if url.endswith("/events"):
            submitted.append(body)
            if body["maintenance"]:
                return {"status": "suppressed", "reason": "maintenance"}
            return {"status": "held", "reason": "notification_not_authorized"}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(production_smoke, "request", fake_request)
    production_smoke.main()
    assert len(submitted) == 2
    assert all(event["event_id"] != "perry-phone-test-001" for event in submitted)
    assert all(event["source"] == "synthetic" for event in submitted)
    assert submitted[0]["maintenance"] is False
    assert submitted[1]["maintenance"] is True


def test_production_smoke_refuses_an_unexpected_alert(monkeypatch):
    monkeypatch.setenv("PERRY_PROD_URL", "http://perry.test")
    monkeypatch.setenv("PERRY_APPROVED_EVENT_ID", "perry-phone-test-001")

    def fake_request(url, body=None):
        if url.endswith("/healthz"):
            return {"status": "ok"}
        return {"status": "alert", "reason": "notification_accepted"}

    monkeypatch.setattr(production_smoke, "request", fake_request)
    with pytest.raises(AssertionError, match="not held"):
        production_smoke.main()


def test_production_smoke_waits_for_a_slow_start(monkeypatch):
    monkeypatch.setenv("PERRY_PROD_URL", "http://perry.test")
    monkeypatch.setenv("PERRY_APPROVED_EVENT_ID", "perry-phone-test-001")
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _seconds: None)
    health = {"count": 0}

    def fake_request(url, _body=None):
        if url.endswith("/healthz"):
            health["count"] += 1
            if health["count"] < 2:
                raise OSError("connection refused during rollout")
            return {"status": "ok"}
        if url.endswith("/events"):
            if _body is not None and _body["maintenance"]:
                return {"status": "suppressed", "reason": "maintenance"}
            return {"status": "held", "reason": "notification_not_authorized"}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(production_smoke, "request", fake_request)
    production_smoke.main()
    assert health["count"] == 2
