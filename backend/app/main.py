import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.ai import router as ai_router
from app.api.chain import router as chain_router
from app.api.merchants import router as merchants_router
from app.api.payments import router as payments_router
from app.cache import check_cache, redis_client
from app.chain_worker import EscrowChainWorker
from app.config import get_settings
from app.database import check_database, engine
from app.middleware import TrustedOriginMiddleware

settings = get_settings()
chain_worker = EscrowChainWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env.lower() != "test" and settings.authorizer_private_key:
        task = asyncio.create_task(chain_worker.run())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    else:
        yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    TrustedOriginMiddleware,
    allowed_origins=settings.cors_origin_list,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(chain_router)
app.include_router(merchants_router)
app.include_router(payments_router)


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness(response: Response) -> dict[str, str]:
    try:
        await check_database()
        await check_cache()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready"}
    return {"status": "ready"}