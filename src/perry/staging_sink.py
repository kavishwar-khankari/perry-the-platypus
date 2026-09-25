"""Disposable HTTP receiver for GitOps staging; never started in production."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class Notification(BaseModel):
    title: str
    body: str
    type: Literal["warning", "info", "failure"]


def create_app() -> FastAPI:
    app = FastAPI(title="Perry staging notification sink", docs_url=None, redoc_url=None)
    received = 0

    @app.post("/notify/global")
    def notify(_message: Notification) -> dict:
        nonlocal received
        received += 1
        return {"success": True}

    @app.get("/calls")
    def calls() -> dict:
        return {"count": received}

    return app


app = create_app()
