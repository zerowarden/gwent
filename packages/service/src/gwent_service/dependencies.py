from __future__ import annotations

from functools import lru_cache

from gwent_service.application.match_service import MatchService
from gwent_service.config import ServiceConfig, default_service_config
from gwent_service.domain.repositories import MatchRepository
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.engine.contracts import EngineAdapter
from gwent_service.infrastructure.memory_repo import InMemoryMatchRepository
from gwent_service.infrastructure.sqlite import SQLiteMatchRepository


@lru_cache(maxsize=1)
def get_service_config() -> ServiceConfig:
    return default_service_config()


@lru_cache(maxsize=1)
def get_engine_adapter() -> EngineAdapter:
    return GwentEngineAdapter(get_service_config())


@lru_cache(maxsize=1)
def get_match_repository() -> MatchRepository:
    config = get_service_config()
    if config.repository_backend == "memory":
        return InMemoryMatchRepository()
    if config.repository_backend == "sqlite":
        return SQLiteMatchRepository(config.sqlite_path)
    raise ValueError(f"Unsupported repository backend: {config.repository_backend!r}")


def get_match_service() -> MatchService:
    return MatchService(
        repository=get_match_repository(),
        adapter=get_engine_adapter(),
    )
