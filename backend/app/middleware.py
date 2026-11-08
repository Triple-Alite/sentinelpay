from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class TrustedOriginMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in self.allowed_origins:
                return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)
        return await call_next(request)