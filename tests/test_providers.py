import asyncio
import json

import httpx
import pytest

from perry.providers import AppriseNotifier, ZenJev


def test_zen_receives_only_structured_synthetic_state_and_a_choice_question():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert body["model"] == "jev-1.13-free"
        assert body["state"] == {"source": "synthetic", "cpu_average_percent": 96}
        assert body["questions"]["alert_decision"]["type"] == "choice"
        assert set(body["questions"]["alert_decision"]["criteria"]) == {"alert", "ignore"}
        assert request.headers["Authorization"] == "Bearer fake-test-key"
        return httpx.Response(200, json={"model": "jev-1.13-free", "answers": {}})

    model = ZenJev(api_key="fake-test-key", transport=httpx.MockTransport(handler))
    answer = asyncio.run(model.decide({"source": "synthetic", "cpu_average_percent": 96}))
    assert answer["model"] == "jev-1.13-free"
    assert len(requests) == 1


def test_zen_rejects_non_synthetic_state_before_network():
    model = ZenJev(
        api_key="fake-test-key",
        transport=httpx.MockTransport(lambda _: pytest.fail("No external request permitted")),
    )
    with pytest.raises(ValueError, match="Only synthetic"):
        asyncio.run(model.decide({"source": "mimir", "cpu_average_percent": 96}))


def test_apprise_receives_a_fixed_json_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/notify/global"
        assert json.loads(request.content) == {
            "title": "[PERRY POC — SYNTHETIC] Example",
            "body": "Invented event only",
            "type": "warning",
        }
        return httpx.Response(200, json={"success": True})

    notifier = AppriseNotifier(
        "http://apprise.test/notify/global", transport=httpx.MockTransport(handler)
    )
    asyncio.run(notifier.send("[PERRY POC — SYNTHETIC] Example", "Invented event only"))
