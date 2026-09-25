"""The two outbound HTTP boundaries; only synthetic state reaches hosted Jev."""

import httpx

QUESTION = {
    "alert_decision": {
        "type": "choice",
        "instructions": "Choose the action for this synthetic operational event.",
        "criteria": {
            "alert": "Sustained high CPU and user-visible HTTP errors outside maintenance",
            "ignore": "No actionable sustained CPU and HTTP error incident",
        },
    }
}


class ZenJev:
    def __init__(
        self,
        api_key: str,
        model_id: str = "jev-1.13-free",
        url: str = "https://opencode.ai/zen/v1/systemone",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.url = url
        self.transport = transport

    async def decide(self, state: dict) -> dict:
        if not self.api_key:
            raise ValueError("PERRY_ZEN_API_KEY is not configured")
        if state.get("source") != "synthetic":
            raise ValueError("Only synthetic events may reach the hosted model")
        async with httpx.AsyncClient(timeout=8.0, transport=self.transport) as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model_id, "state": state, "questions": QUESTION},
            )
            response.raise_for_status()
            return response.json()


class AppriseNotifier:
    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = url
        self.transport = transport

    async def send(self, title: str, body: str) -> None:
        if not self.url:
            raise ValueError("PERRY_APPRISE_URL is not configured")
        async with httpx.AsyncClient(timeout=5.0, transport=self.transport) as client:
            response = await client.post(
                self.url, json={"title": title, "body": body, "type": "warning"}
            )
            response.raise_for_status()
