from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .errors import DomainError
from .routers import admin, auth, resident

app = FastAPI(title="Residente API", version="0.1.0")

if config.cors_origins():
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins(), allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(DomainError)
async def domain_error(_: Request, exc: DomainError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


for r in (auth.router, resident.router, admin.router):
    app.include_router(r, prefix="/api/v1")
