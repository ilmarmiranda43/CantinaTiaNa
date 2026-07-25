from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import require_user, template_context
from app.main_shared import templates


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, _=Depends(require_user)):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context=template_context(request),
    )


@router.get("/health")
def health():
    return {"ok": True}

