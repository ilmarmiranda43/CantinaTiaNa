from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_roles, require_user, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Produto
from app.security import parse_decimal, require_csrf


router = APIRouter(prefix="/produtos", tags=["produtos"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), _=Depends(require_user)):
    items = db.scalars(select(Produto).order_by(Produto.nome)).all()
    return _render(request, "produtos/index.html", items=items)


@router.get("/new", response_class=HTMLResponse)
def create_form(request: Request, _=Depends(require_roles("Admin", "Prop"))):
    return _render(request, "produtos/form.html", item=None, error=None)


def _apply(item: Produto, nome: str, preco: str, quantidade: int, categoria: str) -> str | None:
    try:
        price = parse_decimal(preco)
    except InvalidOperation:
        return "Informe um preço válido."
    if not nome.strip() or price < 0 or quantidade < 0:
        return "Preencha os dados do produto com valores válidos."
    item.nome = nome.strip()
    item.preco = price
    item.quantidade = quantidade
    item.categoria = categoria.strip() or None
    return None


@router.post("/new", response_class=HTMLResponse)
async def create(
    request: Request,
    nome: str = Form(...),
    preco: str = Form(...),
    quantidade: int = Form(0),
    categoria: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = Produto(nome="", preco=Decimal("0"), quantidade=0, data_cadastro=datetime.now())
    error = _apply(item, nome, preco, quantidade, categoria)
    if error:
        return _render(request, "produtos/form.html", item=item, error=error)
    db.add(item)
    db.commit()
    return RedirectResponse("/produtos", status_code=303)


@router.get("/{item_id}/edit", response_class=HTMLResponse)
def edit_form(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    item = db.get(Produto, item_id)
    if not item:
        return RedirectResponse("/produtos", status_code=303)
    return _render(request, "produtos/form.html", item=item, error=None)


@router.post("/{item_id}/edit", response_class=HTMLResponse)
async def edit(
    item_id: int,
    request: Request,
    nome: str = Form(...),
    preco: str = Form(...),
    quantidade: int = Form(0),
    categoria: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = db.get(Produto, item_id)
    if not item:
        return RedirectResponse("/produtos", status_code=303)
    error = _apply(item, nome, preco, quantidade, categoria)
    if error:
        return _render(request, "produtos/form.html", item=item, error=error)
    db.commit()
    return RedirectResponse("/produtos", status_code=303)


@router.post("/{item_id}/delete")
async def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = db.get(Produto, item_id)
    if item:
        db.delete(item)
        try:
            db.commit()
        except Exception:
            db.rollback()
    return RedirectResponse("/produtos", status_code=303)
