from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import AccessDenied, require_user, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Aluno, Compra, CompraItem


router = APIRouter(prefix="/relatorios", tags=["relatórios"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


def _month_limits() -> tuple[datetime, datetime]:
    now = datetime.now()
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year + 1, 1, 1) if now.month == 12 else datetime(now.year, now.month + 1, 1)
    return start, end


@router.get("", response_class=HTMLResponse)
def balances(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    start, end = _month_limits()
    query = select(Aluno).options(joinedload(Aluno.responsavel)).order_by(Aluno.nome)
    if "Aluno" in request.state.roles:
        query = query.where(Aluno.application_user_id == user.id)
    items = []
    for aluno in db.scalars(query).all():
        consumed = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(Compra.valor_total), 0)).where(
                    Compra.aluno_id == aluno.id, Compra.data >= start, Compra.data < end
                )
            )
            or 0
        )
        limit = aluno.responsavel.valor_para_cantina
        items.append(
            {
                "aluno": aluno,
                "limite": limit,
                "consumido": consumed,
                "disponivel": max(Decimal("0"), limit - consumed),
            }
        )
    return _render(request, "relatorios/index.html", items=items)


@router.get("/aluno/{aluno_id}", response_class=HTMLResponse)
def student_details(
    aluno_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    aluno = db.scalar(
        select(Aluno).options(joinedload(Aluno.responsavel)).where(Aluno.id == aluno_id)
    )
    if not aluno:
        return RedirectResponse("/relatorios", status_code=303)
    if "Aluno" in request.state.roles and aluno.application_user_id != user.id:
        raise AccessDenied()
    compras = db.scalars(
        select(Compra)
        .options(selectinload(Compra.itens).joinedload(CompraItem.produto))
        .where(Compra.aluno_id == aluno.id)
        .order_by(Compra.data.desc())
    ).all()
    return _render(
        request, "relatorios/student_details.html", aluno=aluno, compras=compras
    )
