"""A single synthetic, read-only contract check against the real hosted Jev endpoint."""

import asyncio
import os

from perry.app import ModelResponse
from perry.providers import ZenJev


async def check() -> None:
    key = os.getenv("PERRY_ZEN_API_KEY", "")
    if not key:
        raise SystemExit("PERRY_ZEN_API_KEY is missing (do not print or commit the key)")
    reply = ModelResponse.model_validate(
        await ZenJev(api_key=key).decide(
            {
                "source": "synthetic",
                "node": "demo-node",
                "cpu_average_percent": 96,
                "window_seconds": 360,
                "http_error_percent": 8,
                "maintenance": False,
            }
        )
    )
    if reply.model != "jev-1.13-free" or set(reply.answers) != {"alert_decision"}:
        raise SystemExit("Unexpected Jev model or response key")
    answer = reply.answers["alert_decision"]
    if set(answer.probabilities) != {"alert", "ignore"}:
        raise SystemExit("Expected both Choice options")
    print(f"Real Jev contract accepted synthetic Choice; model={reply.model}.")
    print("This does not validate model accuracy or send a notification.")


if __name__ == "__main__":
    asyncio.run(check())
