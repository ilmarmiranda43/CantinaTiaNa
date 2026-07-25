from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import require_roles, require_user, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Aluno, Responsavel, User
from app.security import require_csrf


router = APIRouter(prefix="/alunos", tags=["alunos"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), _=Depends(require_user)):
    query = select(Aluno).options(joinedload(Aluno.responsavel)).order_by(Aluno.nome)
    if "Aluno" in request.state.roles:
        query = query.where(Aluno.application_user_id == request.state.user.id)
    items = db.scalars(query).all()
    return _render(request, "alunos/index.html", items=items)


def _form_data(db: Session):
    responsaveis = db.scalars(select(Responsavel).order_by(Responsavel.nome)).all()
    users = db.scalars(select(User).order_by(User.nome)).all()
    return responsaveis, users


@router.get("/new", response_class=HTMLResponse)
def create_form(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    responsaveis, users = _form_data(db)
    return _render(
        request, "alunos/form.html", item=None, responsaveis=responsaveis, users=users, error=None
    )


@router.post("/new", response_class=HTMLResponse)
async def create(
    request: Request,
    nome: str = Form(...),
    data_nascimento: str = Form(...),
    serie: str = Form(...),
    responsavel_id: int = Form(...),
    application_user_id: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    responsavel = db.get(Responsavel, responsavel_id)
    responsaveis, users = _form_data(db)
    try:
        birth = datetime.strptime(data_nascimento, "%Y-%m-%d")
    except ValueError:
        birth = None
    error = None
    if not responsavel:
        error = "Responsável não encontrado."
    elif not nome.strip() or not serie.strip() or not birth:
        error = "Preencha nome, data de nascimento e série."
    if error:
        return _render(
            request,
            "alunos/form.html",
            item=None,
            responsaveis=responsaveis,
            users=users,
            error=error,
        )
    item = Aluno(
        nome=nome.strip(),
        data_nascimento=birth,
        serie=serie.strip(),
        valor_disponivel=responsavel.valor_para_cantina,
        responsavel_id=responsavel.id,
        application_user_id=application_user_id or None,
    )
    db.add(item)
    db.commit()
    return RedirectResponse("/alunos", status_code=303)


@router.get("/{item_id}/edit", response_class=HTMLResponse)
def edit_form(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    item = db.get(Aluno, item_id)
    if not item:
        return RedirectResponse("/alunos", status_code=303)
    responsaveis, users = _form_data(db)
    return _render(
        request,
        "alunos/form.html",
        item=item,
        responsaveis=responsaveis,
        users=users,
        error=None,
    )


@router.post("/{item_id}/edit", response_class=HTMLResponse)
async def edit(
    item_id: int,
    request: Request,
    nome: str = Form(...),
    data_nascimento: str = Form(...),
    serie: str = Form(...),
    responsavel_id: int = Form(...),
    application_user_id: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = db.get(Aluno, item_id)
    responsavel = db.get(Responsavel, responsavel_id)
    responsaveis, users = _form_data(db)
    try:
        birth = datetime.strptime(data_nascimento, "%Y-%m-%d")
    except ValueError:
        birth = None
    error = None
    if not item or not responsavel:
        error = "Aluno ou responsável não encontrado."
    elif not nome.strip() or not serie.strip() or not birth:
        error = "Preencha nome, data de nascimento e série."
    if error:
        return _render(
            request,
            "alunos/form.html",
            item=item,
            responsaveis=responsaveis,
            users=users,
            error=error,
        )
    item.nome = nome.strip()
    item.data_nascimento = birth
    item.serie = serie.strip()
    item.responsavel_id = responsavel.id
    item.application_user_id = application_user_id or None
    db.commit()
    return RedirectResponse("/alunos", status_code=303)


@router.post("/{item_id}/delete")
async def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    item = db.get(Aluno, item_id)
    if item and not item.compras:
        db.delete(item)
        db.commit()
    return RedirectResponse("/alunos", status_code=303)

