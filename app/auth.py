from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Role, User, UserRole
from app.security import csrf_token


ROLES = ("Admin", "Prop", "Aluno", "Responsavel")


class LoginRequired(Exception):
    pass


class AccessDenied(Exception):
    pass


def roles_for_user(db: Session, user_id: str) -> set[str]:
    rows = db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).scalars()
    return {value for value in rows if value}


def load_request_identity(request: Request) -> None:
    request.state.user = None
    request.state.roles = set()
    user_id = request.session.get("user_id")
    if not user_id:
        return
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user:
            request.state.user = user
            request.state.roles = roles_for_user(db, user.id)
        else:
            request.session.pop("user_id", None)


def require_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise LoginRequired()
    return user


def require_roles(*allowed: str) -> Callable[[Request], User]:
    def dependency(request: Request) -> User:
        user = require_user(request)
        if not set(allowed).intersection(getattr(request.state, "roles", set())):
            raise AccessDenied()
        return user

    return dependency


def require_whatsapp(request: Request) -> User:
    user = require_user(request)
    roles = getattr(request.state, "roles", set())
    if "Admin" not in roles and not user.pode_enviar_whatsapp:
        raise AccessDenied()
    return user


def template_context(request: Request, **values: object) -> dict[str, object]:
    roles = getattr(request.state, "roles", set())
    user = getattr(request.state, "user", None)
    return {
        "request": request,
        "current_user": user,
        "roles": roles,
        "is_admin": "Admin" in roles,
        "is_prop": "Prop" in roles,
        "can_whatsapp": bool(user and ("Admin" in roles or user.pode_enviar_whatsapp)),
        "csrf_token": csrf_token(request),
        **values,
    }

