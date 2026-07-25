from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
from decimal import Decimal
from urllib.parse import urlparse

from fastapi import HTTPException, Request


PRFS = {0: "sha1", 1: "sha256", 2: "sha512"}


def hash_password(password: str, *, iterations: int = 100_000) -> str:
    """Gera um hash compatível com ASP.NET Core Identity v3."""
    salt = os.urandom(16)
    subkey = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, 32)
    payload = b"\x01" + struct.pack(">III", 1, iterations, len(salt)) + salt + subkey
    return base64.b64encode(payload).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        payload = base64.b64decode(password_hash)
    except (ValueError, TypeError):
        return False

    try:
        if payload[0] == 0:
            salt = payload[1:17]
            expected = payload[17:49]
            actual = hashlib.pbkdf2_hmac("sha1", password.encode(), salt, 1_000, 32)
        elif payload[0] == 1 and len(payload) >= 14:
            prf, iterations, salt_length = struct.unpack(">III", payload[1:13])
            algorithm = PRFS.get(prf)
            if not algorithm or iterations <= 0 or salt_length < 8:
                return False
            salt = payload[13 : 13 + salt_length]
            expected = payload[13 + salt_length :]
            if not expected:
                return False
            actual = hashlib.pbkdf2_hmac(
                algorithm, password.encode(), salt, iterations, len(expected)
            )
        else:
            return False
    except (ValueError, IndexError, struct.error):
        return False
    return hmac.compare_digest(actual, expected)


def normalize_identity(value: str) -> str:
    return value.strip().upper()


def csrf_token(request: Request) -> str:
    token = request.session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["_csrf"] = token
    return token


async def require_csrf(request: Request) -> None:
    form = await request.form()
    received = str(form.get("csrf_token", ""))
    expected = str(request.session.get("_csrf", ""))
    if not expected or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=400, detail="Token de segurança inválido. Atualize a página.")


def safe_return_url(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return "/"
    return value


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) in {10, 11}:
        digits = "55" + digits
    return digits


def parse_decimal(value: str) -> Decimal:
    normalized = value.strip().replace("R$", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    return Decimal(normalized)
