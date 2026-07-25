from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import AccessDenied, require_roles, require_user, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Aluno, Compra, CompraItem
from app.security import parse_decimal, require_csrf


router = APIRouter(prefix="/compras", tags=["compras"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


def _own_student(db: Session, user_id: str) -> Aluno | None:
    return db.scalar(select(Aluno).where(Aluno.application_user_id == user_id))


@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    query = (
        select(Compra)
        .options(joinedload(Compra.aluno))
        .order_by(Compra.data.desc())
    )
    student = _own_student(db, user.id)
    if student:
        query = query.where(Compra.aluno_id == student.id)
    items = db.scalars(query).all()
    return _render(request, "compras/index.html", items=items)


@router.get("/new", response_class=HTMLResponse)
def create_form(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    alunos = db.scalars(select(Aluno).order_by(Aluno.nome)).all()
    return _render(request, "compras/form.html", alunos=alunos, error=None)


@router.post("/new", response_class=HTMLResponse)
async def create(
    request: Request,
    aluno_id: int = Form(...),
    valor_total: str = Form(...),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    alunos = db.scalars(select(Aluno).order_by(Aluno.nome)).all()
    aluno = db.get(Aluno, aluno_id)
    try:
        total = parse_decimal(valor_total)
    except InvalidOperation:
        total = Decimal("-1")
    if not aluno or total <= 0:
        return _render(
            request, "compras/form.html", alunos=alunos, error="Informe aluno e valor válidos."
        )
    if aluno.valor_disponivel < total:
        return _render(request, "compras/form.html", alunos=alunos, error="Saldo insuficiente.")
    aluno.valor_disponivel -= total
    db.add(Compra(aluno_id=aluno.id, data=datetime.now(), valor_total=total))
    db.commit()
    return RedirectResponse("/compras", status_code=303)


@router.get("/{item_id}", response_class=HTMLResponse)
def details(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    item = db.scalar(
        select(Compra)
        .options(
            joinedload(Compra.aluno),
            selectinload(Compra.itens).joinedload(CompraItem.produto),
        )
        .where(Compra.id == item_id)
    )
    if not item:
        return RedirectResponse("/compras", status_code=303)
    student = _own_student(db, user.id)
    if student and item.aluno_id != student.id:
        raise AccessDenied()
    return _render(request, "compras/details.html", item=item)
