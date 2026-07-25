from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_roles, require_user, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Responsavel
from app.security import parse_decimal, require_csrf


router = APIRouter(prefix="/responsaveis", tags=["responsáveis"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), _=Depends(require_user)):
    items = db.scalars(select(Responsavel).order_by(Responsavel.nome)).all()
    return _render(request, "responsaveis/index.html", items=items)


@router.get("/new", response_class=HTMLResponse)
def create_form(request: Request, _=Depends(require_roles("Admin", "Prop"))):
    return _render(request, "responsaveis/form.html", item=None, error=None)


def _apply(
    item: Responsavel,
    nome: str,
    valor_para_cantina: str,
    fone: str,
    email: str,
    dia_pgto: str,
) -> str | None:
    try:
        valor = parse_decimal(valor_para_cantina)
    except InvalidOperation:
        return "Informe um valor válido."
    if not nome.strip():
        return "O nome é obrigatório."
    if valor < 0:
        return "O valor deve ser positivo."
    try:
        dia = int(dia_pgto) if dia_pgto.strip() else None
    except ValueError:
        return "O dia do pagamento deve ser um número."
    if dia is not None and not 1 <= dia <= 31:
        return "O dia do pagamento deve estar entre 1 e 31."
    item.nome = nome.strip()
    item.valor_para_cantina = valor
    item.fone = fone.strip() or None
    item.email = email.strip() or None
    item.dia_pgto = dia
    return None


@router.post("/new", response_class=HTMLResponse)
async def create(
    request: Request,
    nome: str = Form(...),
    valor_para_cantina: str = Form(...),
    fone: str = Form(""),
    email: str = Form(""),
    dia_pgto: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = Responsavel(nome="", valor_para_cantina=Decimal("0"))
    error = _apply(item, nome, valor_para_cantina, fone, email, dia_pgto)
    if error:
        return _render(request, "responsaveis/form.html", item=item, error=error)
    db.add(item)
    db.commit()
    return RedirectResponse("/responsaveis", status_code=303)


@router.get("/{item_id}/edit", response_class=HTMLResponse)
def edit_form(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    item = db.get(Responsavel, item_id)
    if not item:
        return RedirectResponse("/responsaveis", status_code=303)
    return _render(request, "responsaveis/form.html", item=item, error=None)


@router.post("/{item_id}/edit", response_class=HTMLResponse)
async def edit(
    item_id: int,
    request: Request,
    nome: str = Form(...),
    valor_para_cantina: str = Form(...),
    fone: str = Form(""),
    email: str = Form(""),
    dia_pgto: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = db.get(Responsavel, item_id)
    if not item:
        return RedirectResponse("/responsaveis", status_code=303)
    error = _apply(item, nome, valor_para_cantina, fone, email, dia_pgto)
    if error:
        return _render(request, "responsaveis/form.html", item=item, error=error)
    db.commit()
    return RedirectResponse("/responsaveis", status_code=303)


@router.post("/{item_id}/delete")
async def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = db.get(Responsavel, item_id)
    if item:
        try:
            db.delete(item)
            db.commit()
        except IntegrityError:
            db.rollback()
    return RedirectResponse("/responsaveis", status_code=303)
