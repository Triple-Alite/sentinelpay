from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings


def _async_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    return database_url


settings = get_settings()
engine = create_async_engine(_async_database_url(settings.database_url), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def check_database() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def get_db():
    async with SessionLocal() as session:
        yield session