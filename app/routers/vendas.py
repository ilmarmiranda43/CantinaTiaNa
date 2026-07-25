from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import AccessDenied, require_user, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Aluno, Compra, CompraItem, Produto
from app.security import require_csrf


router = APIRouter(prefix="/vendas", tags=["vendas"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


def _own_student(db: Session, user_id: str) -> Aluno | None:
    return db.scalar(select(Aluno).where(Aluno.application_user_id == user_id))


def _month_limits(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, 1)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1)
    else:
        end = datetime(now.year, now.month + 1, 1)
    return start, end


def _limit_info(db: Session, aluno: Aluno) -> dict[str, Decimal]:
    start, end = _month_limits(datetime.now())
    consumed = db.scalar(
        select(func.coalesce(func.sum(Compra.valor_total), 0)).where(
            Compra.aluno_id == aluno.id,
            Compra.data >= start,
            Compra.data < end,
        )
    )
    limit = aluno.responsavel.valor_para_cantina if aluno.responsavel else Decimal("0")
    consumed = Decimal(consumed or 0)
    return {
        "limite": limit,
        "consumido": consumed,
        "disponivel": max(Decimal("0"), limit - consumed),
    }


@router.get("/new", response_class=HTMLResponse)
def create_form(
    request: Request,
    aluno_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    own = _own_student(db, user.id)
    if own:
        aluno_id = own.id
        alunos = [own]
    else:
        alunos = db.scalars(select(Aluno).order_by(Aluno.nome)).all()
    produtos = db.scalars(select(Produto).order_by(Produto.nome)).all()
    selected = db.scalar(
        select(Aluno).options(joinedload(Aluno.responsavel)).where(Aluno.id == aluno_id)
    ) if aluno_id else None
    limits = _limit_info(db, selected) if selected else None
    return _render(
        request,
        "vendas/form.html",
        alunos=alunos,
        produtos=produtos,
        selected_id=aluno_id,
        limits=limits,
        error=None,
    )


@router.post("/new", response_class=HTMLResponse)
async def create(
    request: Request,
    aluno_id: int = Form(...),
    produto_id: list[int] = Form(...),
    quantidade: list[int] = Form(...),
    db: Session = Depends(get_db),
    user=Depends(require_user),
    _=Depends(require_csrf),
):
    own = _own_student(db, user.id)
    if own and aluno_id != own.id:
        raise AccessDenied()
    aluno = db.scalar(
        select(Aluno).options(joinedload(Aluno.responsavel)).where(Aluno.id == aluno_id)
    )
    alunos = [own] if own else db.scalars(select(Aluno).order_by(Aluno.nome)).all()
    produtos = db.scalars(select(Produto).order_by(Produto.nome)).all()
    limits = _limit_info(db, aluno) if aluno else None
    pairs = [(pid, qty) for pid, qty in zip(produto_id, quantidade) if pid > 0 and qty > 0]
    error = None
    if not aluno:
        error = "Aluno não encontrado."
    elif not pairs:
        error = "Selecione ao menos um produto com quantidade."
    product_map = {item.id: item for item in produtos}
    if any(pid not in product_map for pid, _qty in pairs):
        error = "Um dos produtos selecionados não foi encontrado."
    total = sum((product_map[pid].preco * qty for pid, qty in pairs), Decimal("0"))
    if limits and total > limits["disponivel"]:
        error = (
            f"Limite insuficiente. Disponível: {limits['disponivel']:.2f}; "
            f"total da venda: {total:.2f}."
        )
    if error:
        return _render(
            request,
            "vendas/form.html",
            alunos=alunos,
            produtos=produtos,
            selected_id=aluno_id,
            limits=limits,
            error=error,
        )
    compra = Compra(aluno_id=aluno.id, data=datetime.now(), valor_total=total)
    compra.itens = [
        CompraItem(
            produto_id=pid,
            quantidade=qty,
            preco_unitario=product_map[pid].preco,
        )
        for pid, qty in pairs
    ]
    db.add(compra)
    db.commit()
    return RedirectResponse(f"/compras/{compra.id}?success=1", status_code=303)


@router.get("/limit/{aluno_id}")
def limit(
    aluno_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    own = _own_student(db, user.id)
    if own and own.id != aluno_id:
        raise AccessDenied()
    aluno = db.scalar(
        select(Aluno).options(joinedload(Aluno.responsavel)).where(Aluno.id == aluno_id)
    )
    if not aluno:
        return JSONResponse({"limite": 0, "consumidoMes": 0, "disponivel": 0})
    info = _limit_info(db, aluno)
    return JSONResponse(
        {
            "limite": float(info["limite"]),
            "consumidoMes": float(info["consumido"]),
            "disponivel": float(info["disponivel"]),
        }
    )

