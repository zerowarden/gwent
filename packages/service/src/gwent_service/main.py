from __future__ import annotations

from fastapi import FastAPI

from gwent_service.api import register_exception_handlers, router
from gwent_service.dto import HealthResponse

app = FastAPI(title="gwent_service")
register_exception_handlers(app)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


app.include_router(router)
