from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import (
    AccessDenied,
    require_roles,
    require_user,
    roles_for_user,
    template_context,
)
from app.database import get_db
from app.main_shared import templates
from app.models import Role, User, UserRole
from app.security import (
    hash_password,
    normalize_identity,
    require_csrf,
    safe_return_url,
    verify_password,
)


router = APIRouter(prefix="/account", tags=["conta"])


def _render(request: Request, name: str, **values):
    return templates.TemplateResponse(
        request=request, name=name, context=template_context(request, **values)
    )


def _role_choices(roles: set[str]) -> list[str]:
    if "Admin" in roles:
        return ["Admin", "Prop", "Aluno", "Responsavel"]
    if "Prop" in roles:
        return ["Aluno", "Responsavel"]
    return []


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, return_url: str = ""):
    if getattr(request.state, "user", None):
        return RedirectResponse("/", status_code=303)
    return _render(request, "account/login.html", error=None, return_url=return_url, values={})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember_me: bool = Form(False),
    return_url: str = Form(""),
    db: Session = Depends(get_db),
    _=Depends(require_csrf),
):
    normalized = normalize_identity(email)
    user = db.scalar(
        select(User).where(
            (User.normalized_email == normalized)
            | (User.normalized_user_name == normalized)
        )
    )
    if not user or not verify_password(password, user.password_hash):
        return _render(
            request,
            "account/login.html",
            error="Login inválido.",
            return_url=return_url,
            values={"email": email, "remember_me": remember_me},
        )
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["remember_me"] = remember_me
    return RedirectResponse(safe_return_url(return_url), status_code=303)


@router.post("/logout")
async def logout(request: Request, _user=Depends(require_user), _=Depends(require_csrf)):
    request.session.clear()
    return RedirectResponse("/account/login", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def users(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    result = []
    for user in db.scalars(select(User).order_by(User.nome, User.email)).all():
        result.append({"user": user, "roles": sorted(roles_for_user(db, user.id))})
    return _render(request, "account/users.html", users=result)


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, _=Depends(require_roles("Admin", "Prop"))):
    return _render(
        request,
        "account/register.html",
        choices=_role_choices(request.state.roles),
        error=None,
        values={},
    )


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(""),
    ra: str = Form(""),
    role: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    pode_enviar_whatsapp: bool = Form(False),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    choices = _role_choices(request.state.roles)
    values = {
        "nome": nome,
        "email": email,
        "phone_number": phone_number,
        "ra": ra,
        "role": role,
        "pode_enviar_whatsapp": pode_enviar_whatsapp,
    }
    error = None
    normalized = normalize_identity(email)
    if role not in choices:
        error = "Você não pode cadastrar esse perfil."
    elif password != confirm_password:
        error = "As senhas não coincidem."
    elif len(password) < 6:
        error = "A senha deve ter pelo menos 6 caracteres."
    elif db.scalar(select(User.id).where(User.normalized_email == normalized)):
        error = "Já existe um usuário com este e-mail."
    role_record = db.scalar(select(Role).where(Role.normalized_name == role.upper()))
    if not role_record:
        error = "Perfil não encontrado no banco de dados."
    if error:
        return _render(
            request,
            "account/register.html",
            choices=choices,
            error=error,
            values=values,
        )

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        user_name=email.strip(),
        normalized_user_name=normalized,
        email=email.strip(),
        normalized_email=normalized,
        email_confirmed=False,
        password_hash=hash_password(password),
        security_stamp=str(uuid.uuid4()),
        concurrency_stamp=str(uuid.uuid4()),
        phone_number=phone_number.strip(),
        phone_number_confirmed=False,
        two_factor_enabled=False,
        lockout_enabled=True,
        access_failed_count=0,
        nome=nome.strip(),
        ra=ra.strip(),
        pode_enviar_whatsapp=(
            "Admin" in request.state.roles and (role == "Admin" or pode_enviar_whatsapp)
        ),
    )
    db.add(user)
    db.add(UserRole(user_id=user_id, role_id=role_record.id))
    db.commit()
    return RedirectResponse("/account/users", status_code=303)


def _editable_user(request: Request, db: Session, user_id: str) -> tuple[User, set[str]]:
    user = db.get(User, user_id)
    if not user:
        raise AccessDenied()
    target_roles = roles_for_user(db, user.id)
    if "Admin" not in request.state.roles and not target_roles.issubset({"Aluno", "Responsavel"}):
        raise AccessDenied()
    return user, target_roles


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
def edit_form(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("Admin", "Prop")),
):
    user, target_roles = _editable_user(request, db, user_id)
    return _render(
        request,
        "account/edit.html",
        target=user,
        target_roles=target_roles,
        error=None,
    )


@router.post("/users/{user_id}/edit", response_class=HTMLResponse)
async def edit(
    user_id: str,
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(""),
    ra: str = Form(""),
    pode_enviar_whatsapp: bool = Form(False),
    db: Session = Depends(get_db),
    _user=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    user, target_roles = _editable_user(request, db, user_id)
    normalized = normalize_identity(email)
    duplicate = db.scalar(
        select(User.id).where(User.normalized_email == normalized, User.id != user.id)
    )
    if duplicate:
        return _render(
            request,
            "account/edit.html",
            target=user,
            target_roles=target_roles,
            error="Já existe um usuário com este e-mail.",
        )
    user.nome = nome.strip()
    user.email = email.strip()
    user.user_name = email.strip()
    user.normalized_email = normalized
    user.normalized_user_name = normalized
    user.phone_number = phone_number.strip()
    user.ra = ra.strip()
    if "Admin" in request.state.roles:
        user.pode_enviar_whatsapp = "Admin" in target_roles or pode_enviar_whatsapp
    db.commit()
    return RedirectResponse("/account/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current=Depends(require_roles("Admin", "Prop")),
    _=Depends(require_csrf),
):
    if current.id == user_id:
        raise AccessDenied()
    user, _target_roles = _editable_user(request, db, user_id)
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.delete(user)
    db.commit()
    return RedirectResponse("/account/users", status_code=303)

