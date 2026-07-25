from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.config import get_settings


class WhatsAppServiceError(Exception):
    pass


@dataclass
class WhatsAppStatus:
    conectado: bool
    status: str
    qr_code: str | None = None
    telefone: str | None = None


class WhatsAppService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _validate(self) -> None:
        if not self.settings.whatsapp_service_url.startswith(("http://", "https://")):
            raise WhatsAppServiceError("WHATSAPP_SERVICE_URL não está configurada corretamente.")
        if not self.settings.whatsapp_api_key:
            raise WhatsAppServiceError("WHATSAPP_API_KEY não está configurada.")
        if not self.settings.whatsapp_session_id:
            raise WhatsAppServiceError("WHATSAPP_SESSION_ID não está configurada.")

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        self._validate()
        url = self.settings.whatsapp_service_url.rstrip("/") + "/" + path.lstrip("/")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.whatsapp_timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=json,
                    headers={"X-API-Key": self.settings.whatsapp_api_key},
                )
        except httpx.TimeoutException as exc:
            raise WhatsAppServiceError("O serviço de WhatsApp demorou demais para responder.") from exc
        except httpx.HTTPError as exc:
            raise WhatsAppServiceError(
                f"Não foi possível acessar o serviço de WhatsApp: {exc}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise WhatsAppServiceError("O serviço de WhatsApp retornou uma resposta inválida.") from exc
        if not response.is_success or payload.get("ok") is not True:
            raise WhatsAppServiceError(
                payload.get("erro") or f"O serviço de WhatsApp retornou HTTP {response.status_code}."
            )
        return payload

    @staticmethod
    def _status(payload: dict) -> WhatsAppStatus:
        session = payload.get("sessao") or {}
        return WhatsAppStatus(
            conectado=bool(payload.get("conectado")),
            status=payload.get("status") or "desconectado",
            qr_code=payload.get("qr_code"),
            telefone=session.get("telefone"),
        )

    async def get_status(self) -> WhatsAppStatus:
        session = quote(self.settings.whatsapp_session_id, safe="")
        return self._status(await self._request("GET", f"sessions/{session}/status"))

    async def connect(self) -> WhatsAppStatus:
        session = quote(self.settings.whatsapp_session_id, safe="")
        return self._status(await self._request("POST", f"sessions/{session}/connect"))

    async def send(self, telefone: str, mensagem: str) -> dict:
        return await self._request(
            "POST",
            "send",
            {
                "session_id": self.settings.whatsapp_session_id,
                "telefone": telefone,
                "mensagem": mensagem,
            },
        )
