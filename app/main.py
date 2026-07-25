from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.auth import AccessDenied, LoginRequired, load_request_identity, template_context
from app.bootstrap import initialize_database
from app.config import get_settings
from app.main_shared import BASE_DIR, templates
from app.routers import (
    account,
    alunos,
    compras,
    home,
    produtos,
    relatorios,
    responsaveis,
    vendas,
    whatsapp,
)


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


async def identity_middleware(request: Request, call_next):
    load_request_identity(request)
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=identity_middleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="cantina_session",
    max_age=60 * 60 * 24 * 14,
    same_site="lax",
    https_only=settings.force_https_cookie,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

for router in (
    home.router,
    account.router,
    alunos.router,
    responsaveis.router,
    compras.router,
    produtos.router,
    vendas.router,
    relatorios.router,
    whatsapp.router,
):
    app.include_router(router)


@app.exception_handler(LoginRequired)
async def login_required(request: Request, _exc: LoginRequired):
    return RedirectResponse(
        f"/account/login?return_url={request.url.path}", status_code=303
    )


@app.exception_handler(AccessDenied)
async def access_denied(request: Request, _exc: AccessDenied):
    return templates.TemplateResponse(
        request=request,
        name="account/access_denied.html",
        context=template_context(request),
        status_code=403,
    )

