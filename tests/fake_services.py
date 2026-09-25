"""Local-only HTTP doubles for testing Perry's built container."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

calls = {"jev": 0, "apprise": []}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/calls":
            self.respond(200, calls)
        else:
            self.respond(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/v1/systemone":
            if body.get("state", {}).get("source") != "synthetic":
                self.respond(400, {"error": "synthetic only"})
                return
            calls["jev"] += 1
            self.respond(
                200,
                {
                    "model": "jev-1.13-free",
                    "answers": {
                        "alert_decision": {
                            "type": "choice",
                            "choice": "alert",
                            "confidence": 1.0,
                            "probabilities": {"alert": 1.0, "ignore": 0.0},
                        }
                    },
                },
            )
        elif self.path == "/notify/global":
            calls["apprise"].append(body)
            # Match the homelab Apprise image's real success contract: 204, empty body.
            self.send_response(204)
            self.end_headers()
        else:
            self.respond(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 18081), Handler).serve_forever()
