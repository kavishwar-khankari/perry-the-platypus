from fastapi.testclient import TestClient

from perry.staging_sink import create_app


def test_staging_sink_counts_requests_without_storing_bodies():
    client = TestClient(create_app())
    assert client.get("/calls").json() == {"count": 0}
    response = client.post(
        "/notify/global",
        json={
            "title": "[PERRY POC — SYNTHETIC] Example",
            "body": "Synthetic test message",
            "type": "warning",
        },
    )
    assert response.status_code == 200
    assert client.get("/calls").json() == {"count": 1}
    assert "Synthetic test message" not in client.get("/calls").text
