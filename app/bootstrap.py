from __future__ import annotations

import uuid

from sqlalchemy import inspect, select, text

from app.auth import ROLES
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import Role, User, UserRole
from app.security import hash_password, normalize_identity


def initialize_database() -> None:
    Base.metadata.create_all(engine)
    _ensure_legacy_columns()
    _seed_roles_and_admin()


def _ensure_legacy_columns() -> None:
    inspector = inspect(engine)
    if "AspNetUsers" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("AspNetUsers")}
    if "PodeEnviarWhatsApp" in columns:
        return
    dialect = engine.dialect.name
    sql = (
        'ALTER TABLE "AspNetUsers" ADD COLUMN "PodeEnviarWhatsApp" BOOLEAN NOT NULL DEFAULT FALSE'
        if dialect != "sqlite"
        else 'ALTER TABLE "AspNetUsers" ADD COLUMN "PodeEnviarWhatsApp" BOOLEAN NOT NULL DEFAULT 0'
    )
    with engine.begin() as connection:
        connection.execute(text(sql))


def _seed_roles_and_admin() -> None:
    settings = get_settings()
    with SessionLocal.begin() as db:
        role_map: dict[str, Role] = {}
        for name in ROLES:
            role = db.scalar(select(Role).where(Role.normalized_name == name.upper()))
            if not role:
                role = Role(
                    id=str(uuid.uuid4()),
                    name=name,
                    normalized_name=name.upper(),
                    concurrency_stamp=str(uuid.uuid4()),
                )
                db.add(role)
                db.flush()
            role_map[name] = role

        admins = db.scalars(
            select(User).join(UserRole, UserRole.user_id == User.id).where(
                UserRole.role_id == role_map["Admin"].id
            )
        ).all()
        for admin in admins:
            admin.pode_enviar_whatsapp = True

        if not settings.admin_email or not settings.admin_password:
            return
        normalized = normalize_identity(settings.admin_email)
        admin = db.scalar(select(User).where(User.normalized_email == normalized))
        if not admin:
            admin = User(
                id=str(uuid.uuid4()),
                user_name=settings.admin_email,
                normalized_user_name=normalized,
                email=settings.admin_email,
                normalized_email=normalized,
                email_confirmed=True,
                password_hash=hash_password(settings.admin_password),
                security_stamp=str(uuid.uuid4()),
                concurrency_stamp=str(uuid.uuid4()),
                phone_number="",
                phone_number_confirmed=False,
                two_factor_enabled=False,
                lockout_enabled=True,
                access_failed_count=0,
                nome=settings.admin_name,
                ra="",
                pode_enviar_whatsapp=True,
            )
            db.add(admin)
            db.flush()
        existing_link = db.get(UserRole, (admin.id, role_map["Admin"].id))
        if not existing_link:
            db.add(UserRole(user_id=admin.id, role_id=role_map["Admin"].id))

