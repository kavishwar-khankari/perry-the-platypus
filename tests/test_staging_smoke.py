import pytest

from perry import staging_smoke


def test_post_sync_journey_requires_real_decision_and_no_maintenance_message(monkeypatch):
    monkeypatch.setenv("PERRY_STAGE_URL", "http://perry.test")
    monkeypatch.setenv("PERRY_STAGE_SINK_URL", "http://sink.test")
    monkeypatch.setenv("PERRY_STAGE_EVENT_ID", "staging-demo")
    submitted = []

    def fake_request(url, body=None):
        if url.endswith("/healthz"):
            return {"status": "ok"}
        if url.endswith("/events"):
            submitted.append(body)
            return (
                {"status": "suppressed", "reason": "maintenance"}
                if body["maintenance"]
                else {"status": "alert", "choice": "alert"}
            )
        if "/decisions/" in url:
            return {"status": "alert"}
        if url.endswith("/calls"):
            return {"count": sum(not event["maintenance"] for event in submitted)}
        raise AssertionError(f"Unexpected staging call: {url}")

    monkeypatch.setattr(staging_smoke, "request", fake_request)
    staging_smoke.main()
    assert [event["maintenance"] for event in submitted] == [False, True]
    assert submitted[0]["source"] == "synthetic"


def test_staging_smoke_does_not_accept_an_old_notification(monkeypatch):
    monkeypatch.setenv("PERRY_STAGE_URL", "http://perry.test")
    monkeypatch.setenv("PERRY_STAGE_SINK_URL", "http://sink.test")
    monkeypatch.setenv("PERRY_STAGE_EVENT_PREFIX", "stage-")
    monkeypatch.delenv("PERRY_STAGE_EVENT_ID", raising=False)

    def fake_request(url, _body=None):
        if url.endswith("/healthz"):
            return {"status": "ok"}
        if url.endswith("/calls"):
            return {"count": 1}  # from an earlier run
        if url.endswith("/events"):
            return {"status": "alert", "choice": "alert"}
        if "/decisions/" in url:
            return {"status": "alert"}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(staging_smoke, "request", fake_request)
    with pytest.raises(AssertionError, match="one new alert"):
        staging_smoke.main()


def test_smoke_waits_for_a_slow_start(monkeypatch):
    monkeypatch.setenv("PERRY_STAGE_URL", "http://perry.test")
    monkeypatch.setenv("PERRY_STAGE_SINK_URL", "http://sink.test")
    monkeypatch.setenv("PERRY_STAGE_EVENT_PREFIX", "stage-")
    monkeypatch.setattr(staging_smoke.time, "sleep", lambda _seconds: None)
    health = {"count": 0}
    submitted = []

    def fake_request(url, body=None):
        if url.endswith("/healthz"):
            health["count"] += 1
            if health["count"] < 3:
                raise OSError("connection refused during rollout")
            return {"status": "ok"}
        if url.endswith("/events"):
            submitted.append(body)
            return (
                {"status": "suppressed", "reason": "maintenance"}
                if body["maintenance"]
                else {"status": "alert", "choice": "alert"}
            )
        if "/decisions/" in url:
            return {"status": "alert"}
        if url.endswith("/calls"):
            return {"count": sum(not event["maintenance"] for event in submitted)}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(staging_smoke, "request", fake_request)
    staging_smoke.main()
    assert health["count"] == 3
