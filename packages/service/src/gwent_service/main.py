from __future__ import annotations

from fastapi import FastAPI

from gwent_service.api.errors import register_exception_handlers
from gwent_service.api.routers.health import router as health_router
from gwent_service.api.routers.matches import router as matches_router

app = FastAPI(title="gwent_service")
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(matches_router)
