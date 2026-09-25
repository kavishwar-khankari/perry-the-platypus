import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Literal, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source: Literal["synthetic"]
    node: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    cpu_samples_percent: list[Annotated[float, Field(ge=0, le=100)]] = Field(
        min_length=1, max_length=120
    )
    sample_interval_seconds: int = Field(ge=1, le=3600)
    http_error_percent: float = Field(ge=0, le=100)
    maintenance: bool


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: Literal["alert", "ignore"]
    probabilities: dict[Literal["alert", "ignore"], float]
    confidence: float = Field(ge=0, le=1)


class ModelResponse(BaseModel):
    model: str
    answers: dict[str, ChoiceAnswer]


class Model(Protocol):
    async def decide(self, state: dict) -> dict: ...


class Notifier(Protocol):
    async def send(self, title: str, body: str) -> None: ...


class DecisionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS decisions "
                "(event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL, "
                "status TEXT NOT NULL, record TEXT NOT NULL)"
            )

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def get(self, event_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT record FROM decisions WHERE event_id=?", (event_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_hash(self, event_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT event_hash FROM decisions WHERE event_id=?", (event_id,)
            ).fetchone()
        return row[0] if row else None

    def claim(self, record: dict, event_hash: str) -> bool:
        with self.connect() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO decisions (event_id, event_hash, status, record) "
                "VALUES (?, ?, ?, ?)",
                (record["event_id"], event_hash, "processing", json.dumps(record)),
            )
            return inserted.rowcount == 1

    def save(self, record: dict) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE decisions SET status=?, record=? WHERE event_id=?",
                (record["status"], json.dumps(record), record["event_id"]),
            )


def create_app(
    *,
    db_path: Path,
    model: Model,
    notifier: Notifier,
    model_id: str = "jev-1.13-free",
    min_confidence: float = 0.7,
    allowed_event_id: str | None = None,
    allowed_event_prefix: str | None = None,
) -> FastAPI:
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")
    if allowed_event_prefix is not None:
        if not re.fullmatch(r"[a-z0-9_-]{1,20}", allowed_event_prefix):
            raise ValueError("Invalid staging event prefix")
        if allowed_event_id is not None:
            raise ValueError("Exact event ID and staging prefix cannot be combined")
    store = DecisionStore(db_path)
    registry = CollectorRegistry()
    outcomes = Counter("perry_decisions_total", "Recorded decisions", ["status"], registry=registry)
    duration = Histogram("perry_event_seconds", "Event processing time", registry=registry)
    app = FastAPI(title="Perry", version="0.1.0")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        # FastAPI's default detail includes `input`, which can echo rejected private telemetry.
        return JSONResponse(status_code=422, content={"detail": "Invalid event payload"})

    @app.get("/healthz")
    def healthz() -> dict:
        with store.connect() as db:
            db.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/decisions/{event_id}")
    def get_decision(event_id: str) -> dict:
        record = store.get(event_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        return record

    @app.post("/events")
    async def process_event(event: Event) -> dict:
        started = time.monotonic()
        cpu_average = round(sum(event.cpu_samples_percent) / len(event.cpu_samples_percent), 2)
        window_seconds = len(event.cpu_samples_percent) * event.sample_interval_seconds
        record = {
            "event_id": event.event_id,
            "node": event.node,
            "source": event.source,
            "cpu_average_percent": cpu_average,
            "window_seconds": window_seconds,
            "http_error_percent": event.http_error_percent,
            "maintenance": event.maintenance,
            "model": None,
            "choice": None,
            "confidence": None,
            "status": "processing",
            "reason": None,
        }
        event_hash = hashlib.sha256(
            json.dumps(event.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if not store.claim(record, event_hash):
            if store.get_hash(event.event_id) != event_hash:
                raise HTTPException(
                    status_code=409, detail="Event ID already used for different data"
                )
            return store.get(event.event_id) or record

        try:
            if event.maintenance:
                record.update(status="suppressed", reason="maintenance")
            elif cpu_average < 90 or window_seconds < 300 or event.http_error_percent < 5:
                record.update(status="suppressed", reason="below_hard_rules")
            elif not (
                (allowed_event_id is None or event.event_id == allowed_event_id)
                and (
                    allowed_event_prefix is None or event.event_id.startswith(allowed_event_prefix)
                )
            ):
                record.update(status="held", reason="notification_not_authorized")
            else:
                try:
                    raw = await model.decide(
                        {
                            "source": "synthetic",
                            "node": event.node,
                            "cpu_average_percent": cpu_average,
                            "window_seconds": window_seconds,
                            "http_error_percent": event.http_error_percent,
                            "maintenance": event.maintenance,
                        }
                    )
                    reply = ModelResponse.model_validate(raw)
                    if reply.model != model_id or set(reply.answers) != {"alert_decision"}:
                        raise ValueError("Unexpected model or question")
                    answer = reply.answers["alert_decision"]
                    if set(answer.probabilities) != {"alert", "ignore"} or any(
                        not 0 <= probability <= 1 for probability in answer.probabilities.values()
                    ):
                        raise ValueError("Invalid option probabilities")
                    record.update(
                        model=reply.model, choice=answer.choice, confidence=answer.confidence
                    )
                    if answer.confidence < min_confidence:
                        record.update(status="held", reason="low_confidence")
                    elif answer.choice == "ignore":
                        record.update(status="suppressed", reason="model_ignored")
                    else:
                        title = f"[PERRY POC — SYNTHETIC] High CPU and errors on {event.node}"
                        body = (
                            f"Synthetic event {event.event_id}: CPU averaged {cpu_average}% "
                            f"over {window_seconds}s; HTTP errors {event.http_error_percent}%. "
                            "Demonstration only — no operational action required."
                        )
                        try:
                            await notifier.send(title, body)
                            record.update(status="alert", reason="notification_accepted")
                        except Exception:
                            record.update(status="delivery_failed", reason="notifier_unavailable")
                except Exception:
                    record.update(status="held", reason="model_unavailable_or_invalid")
        finally:
            store.save(record)
            outcomes.labels(status=record["status"]).inc()
            duration.observe(time.monotonic() - started)
        return record

    return app


def from_environment() -> FastAPI:
    from perry.providers import AppriseNotifier, ZenJev

    prefix = os.getenv("PERRY_STAGE_EVENT_PREFIX") or None
    notifier_url = os.getenv("PERRY_APPRISE_URL", "")
    if prefix and notifier_url != "http://127.0.0.1:18081/notify/global":
        raise ValueError("Staging event prefix requires the loopback fake sink")
    if prefix and os.getenv("PERRY_APPROVED_EVENT_ID"):
        raise ValueError("Staging event prefix cannot authorize a phone event ID")
    return create_app(
        db_path=Path(os.getenv("PERRY_DB_PATH", "/tmp/opencode/perry.sqlite")),
        model=ZenJev(
            api_key=os.getenv("PERRY_ZEN_API_KEY", ""),
            model_id=os.getenv("PERRY_JEV_MODEL", "jev-1.13-free"),
            url=os.getenv("PERRY_ZEN_URL", "https://opencode.ai/zen/v1/systemone"),
        ),
        notifier=AppriseNotifier(notifier_url),
        model_id=os.getenv("PERRY_JEV_MODEL", "jev-1.13-free"),
        min_confidence=float(os.getenv("PERRY_MIN_CONFIDENCE", "0.7")),
        allowed_event_id=None if prefix else os.getenv("PERRY_APPROVED_EVENT_ID", ""),
        allowed_event_prefix=prefix,
    )


app = from_environment()
