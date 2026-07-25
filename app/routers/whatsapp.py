from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import AccessDenied, require_whatsapp, template_context
from app.database import get_db
from app.main_shared import templates
from app.models import Aluno, Compra, CompraItem, Responsavel, WhatsAppMensagem
from app.security import normalize_phone, require_csrf
from app.services.purchase_summary import (
    build_purchase_summary,
    parse_reference_month,
)
from app.services.whatsapp import WhatsAppService, WhatsAppServiceError


router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


async def _page(
    request: Request,
    db: Session,
    *,
    error: str | None = None,
    success: str | None = None,
    values: dict | None = None,
):
    responsaveis = db.scalars(
        select(Responsavel)
        .where(Responsavel.fone.is_not(None), Responsavel.fone != "")
        .order_by(Responsavel.nome)
    ).all()
    alunos = db.scalars(
        select(Aluno)
        .where(Aluno.responsavel_id.in_([item.id for item in responsaveis]))
        .order_by(Aluno.nome)
    ).all()
    history_query = (
        select(WhatsAppMensagem)
        .options(joinedload(WhatsAppMensagem.responsavel))
        .order_by(WhatsAppMensagem.criado_em.desc())
        .limit(20)
    )
    if "Admin" not in request.state.roles:
        history_query = history_query.where(
            WhatsAppMensagem.usuario_id == request.state.user.id
        )
    history = db.scalars(history_query).all()
    status = None
    service_error = None
    try:
        status = await WhatsAppService().get_status()
    except WhatsAppServiceError as exc:
        service_error = str(exc)
    form_values = values or {}
    form_values.setdefault("tipo_mensagem", "livre")
    form_values.setdefault("mes_referencia", datetime.now().strftime("%Y-%m"))
    return templates.TemplateResponse(
        request=request,
        name="whatsapp/index.html",
        context=template_context(
            request,
            responsaveis=responsaveis,
            alunos=alunos,
            history=history,
            status=status,
            service_error=service_error,
            error=error,
            success=success,
            values=form_values,
        ),
    )


def _summary_for_student(
    db: Session,
    responsavel: Responsavel,
    aluno_id: int,
    mes_referencia: str,
):
    aluno = db.get(Aluno, aluno_id)
    if not aluno or aluno.responsavel_id != responsavel.id:
        raise ValueError("O aluno selecionado não pertence a este responsável.")
    reference = parse_reference_month(mes_referencia)
    purchases = db.scalars(
        select(Compra)
        .options(
            selectinload(Compra.itens).joinedload(CompraItem.produto)
        )
        .where(
            Compra.aluno_id == aluno.id,
            Compra.data >= reference.start,
            Compra.data < reference.end,
        )
        .order_by(Compra.data)
    ).all()
    summary = build_purchase_summary(
        responsavel,
        aluno,
        list(purchases),
        reference,
    )
    return aluno, reference, summary


@router.get("", response_class=HTMLResponse)
async def index(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_whatsapp),
):
    return await _page(request, db)


@router.get("/status")
async def connection_status(
    request: Request,
    _user=Depends(require_whatsapp),
):
    if "Admin" not in request.state.roles:
        raise AccessDenied()
    try:
        status = await WhatsAppService().get_status()
        return JSONResponse(
            {
                "ok": True,
                "conectado": status.conectado,
                "status": status.status,
                "qr_code": status.qr_code,
                "telefone": status.telefone,
            }
        )
    except WhatsAppServiceError as exc:
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=503)


@router.get("/purchase-summary")
def purchase_summary(
    responsavel_id: int,
    aluno_id: int,
    mes_referencia: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_whatsapp),
):
    responsavel = db.get(Responsavel, responsavel_id)
    if not responsavel:
        return JSONResponse(
            {"ok": False, "erro": "Responsável não encontrado."},
            status_code=404,
        )
    try:
        aluno, reference, summary = _summary_for_student(
            db,
            responsavel,
            aluno_id,
            mes_referencia,
        )
    except ValueError as exc:
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "mensagem": summary.message,
            "total": float(summary.total),
            "quantidade_compras": summary.purchase_count,
            "compras_omitidas": summary.omitted_count,
            "aluno": aluno.nome,
            "mes_referencia": reference.value,
        }
    )


@router.post("/connect", response_class=HTMLResponse)
async def connect(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_whatsapp),
    _=Depends(require_csrf),
):
    if "Admin" not in request.state.roles:
        raise AccessDenied()
    try:
        status = await WhatsAppService().connect()
        message = (
            "WhatsApp conectado."
            if status.conectado
            else "QR Code gerado. Leia-o pelo aplicativo WhatsApp."
        )
        return await _page(request, db, success=message)
    except WhatsAppServiceError as exc:
        return await _page(request, db, error=str(exc))


@router.post("/send", response_class=HTMLResponse)
async def send(
    request: Request,
    responsavel_id: str = Form(""),
    aluno_id: str = Form(""),
    tipo_mensagem: str = Form("livre"),
    mes_referencia: str = Form(""),
    telefone: str = Form(""),
    mensagem: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(require_whatsapp),
    _=Depends(require_csrf),
):
    responsavel = None
    if responsavel_id:
        try:
            responsavel = db.get(Responsavel, int(responsavel_id))
        except ValueError:
            responsavel = None
        if not responsavel:
            return await _page(request, db, error="Responsável não encontrado.")
        if not responsavel.fone:
            return await _page(request, db, error="O responsável não possui telefone.")
        telefone = responsavel.fone
    normalized = normalize_phone(telefone)
    values = {
        "responsavel_id": responsavel_id,
        "aluno_id": aluno_id,
        "tipo_mensagem": tipo_mensagem,
        "mes_referencia": mes_referencia,
        "telefone": telefone,
        "mensagem": mensagem,
    }
    if len(normalized) < 10 or len(normalized) > 15:
        return await _page(
            request, db, error="Informe um telefone válido com DDD.", values=values
        )
    if tipo_mensagem == "resumo_compras":
        if not responsavel:
            return await _page(
                request,
                db,
                error="Selecione um responsável para enviar a lista de compras.",
                values=values,
            )
        try:
            selected_student_id = int(aluno_id)
        except (TypeError, ValueError):
            return await _page(
                request,
                db,
                error="Selecione o aluno do responsável.",
                values=values,
            )
        try:
            _aluno, reference, summary = _summary_for_student(
                db,
                responsavel,
                selected_student_id,
                mes_referencia,
            )
            mensagem = summary.message
            values["mensagem"] = mensagem
            values["mes_referencia"] = reference.value
        except ValueError as exc:
            return await _page(
                request,
                db,
                error=str(exc),
                values=values,
            )
    elif tipo_mensagem != "livre":
        return await _page(
            request,
            db,
            error="Tipo de mensagem inválido.",
            values=values,
        )

    if not mensagem.strip() or len(mensagem.strip()) > 4096:
        return await _page(
            request, db, error="Informe uma mensagem de até 4096 caracteres.", values=values
        )
    record = WhatsAppMensagem(
        usuario_id=user.id,
        usuario_nome=(user.nome or user.email or "Usuário")[:256],
        responsavel_id=responsavel.id if responsavel else None,
        telefone=normalized,
        mensagem=mensagem.strip(),
        status="Pendente",
        criado_em=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    try:
        result = await WhatsAppService().send(normalized, record.mensagem)
        record.status = "Enviada"
        record.message_id = str(result.get("message_id") or "")[:255] or None
        record.enviado_em = datetime.now(timezone.utc)
        db.commit()
        return await _page(
            request, db, success=f"Mensagem enviada para {normalized}."
        )
    except WhatsAppServiceError as exc:
        record.status = "Erro"
        record.detalhes_erro = str(exc)[:1000]
        db.commit()
        return await _page(request, db, error=str(exc), values=values)



# from __future__ import annotations

# from datetime import datetime, timezone

# from fastapi import APIRouter, Depends, Form, Request
# from fastapi.responses import HTMLResponse, JSONResponse
# from sqlalchemy import select
# from sqlalchemy.orm import Session, joinedload

# from app.auth import AccessDenied, require_whatsapp, template_context
# from app.database import get_db
# from app.main_shared import templates
# from app.models import Responsavel, WhatsAppMensagem
# from app.security import normalize_phone, require_csrf
# from app.services.whatsapp import WhatsAppService, WhatsAppServiceError


# router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


# async def _page(
#     request: Request,
#     db: Session,
#     *,
#     error: str | None = None,
#     success: str | None = None,
#     values: dict | None = None,
# ):
#     responsaveis = db.scalars(
#         select(Responsavel)
#         .where(Responsavel.fone.is_not(None), Responsavel.fone != "")
#         .order_by(Responsavel.nome)
#     ).all()
#     history_query = (
#         select(WhatsAppMensagem)
#         .options(joinedload(WhatsAppMensagem.responsavel))
#         .order_by(WhatsAppMensagem.criado_em.desc())
#         .limit(20)
#     )
#     if "Admin" not in request.state.roles:
#         history_query = history_query.where(
#             WhatsAppMensagem.usuario_id == request.state.user.id
#         )
#     history = db.scalars(history_query).all()
#     status = None
#     service_error = None
#     try:
#         status = await WhatsAppService().get_status()
#     except WhatsAppServiceError as exc:
#         service_error = str(exc)
#     return templates.TemplateResponse(
#         request=request,
#         name="whatsapp/index.html",
#         context=template_context(
#             request,
#             responsaveis=responsaveis,
#             history=history,
#             status=status,
#             service_error=service_error,
#             error=error,
#             success=success,
#             values=values or {},
#         ),
#     )


# @router.get("", response_class=HTMLResponse)
# async def index(
#     request: Request,
#     db: Session = Depends(get_db),
#     _=Depends(require_whatsapp),
# ):
#     return await _page(request, db)


# @router.get("/status")
# async def connection_status(
#     request: Request,
#     _user=Depends(require_whatsapp),
# ):
#     if "Admin" not in request.state.roles:
#         raise AccessDenied()
#     try:
#         status = await WhatsAppService().get_status()
#         return JSONResponse(
#             {
#                 "ok": True,
#                 "conectado": status.conectado,
#                 "status": status.status,
#                 "qr_code": status.qr_code,
#                 "telefone": status.telefone,
#             }
#         )
#     except WhatsAppServiceError as exc:
#         return JSONResponse({"ok": False, "erro": str(exc)}, status_code=503)


# @router.post("/connect", response_class=HTMLResponse)
# async def connect(
#     request: Request,
#     db: Session = Depends(get_db),
#     _user=Depends(require_whatsapp),
#     _=Depends(require_csrf),
# ):
#     if "Admin" not in request.state.roles:
#         raise AccessDenied()
#     try:
#         status = await WhatsAppService().connect()
#         message = (
#             "WhatsApp conectado."
#             if status.conectado
#             else "QR Code gerado. Leia-o pelo aplicativo WhatsApp."
#         )
#         return await _page(request, db, success=message)
#     except WhatsAppServiceError as exc:
#         return await _page(request, db, error=str(exc))


# @router.post("/send", response_class=HTMLResponse)
# async def send(
#     request: Request,
#     responsavel_id: str = Form(""),
#     telefone: str = Form(""),
#     mensagem: str = Form(...),
#     db: Session = Depends(get_db),
#     user=Depends(require_whatsapp),
#     _=Depends(require_csrf),
# ):
#     responsavel = None
#     if responsavel_id:
#         try:
#             responsavel = db.get(Responsavel, int(responsavel_id))
#         except ValueError:
#             responsavel = None
#         if not responsavel:
#             return await _page(request, db, error="Responsável não encontrado.")
#         if not responsavel.fone:
#             return await _page(request, db, error="O responsável não possui telefone.")
#         telefone = responsavel.fone
#     normalized = normalize_phone(telefone)
#     values = {
#         "responsavel_id": responsavel_id,
#         "telefone": telefone,
#         "mensagem": mensagem,
#     }
#     if len(normalized) < 10 or len(normalized) > 15:
#         return await _page(
#             request, db, error="Informe um telefone válido com DDD.", values=values
#         )
#     if not mensagem.strip() or len(mensagem.strip()) > 4096:
#         return await _page(
#             request, db, error="Informe uma mensagem de até 4096 caracteres.", values=values
#         )
#     record = WhatsAppMensagem(
#         usuario_id=user.id,
#         usuario_nome=(user.nome or user.email or "Usuário")[:256],
#         responsavel_id=responsavel.id if responsavel else None,
#         telefone=normalized,
#         mensagem=mensagem.strip(),
#         status="Pendente",
#         criado_em=datetime.now(timezone.utc),
#     )
#     db.add(record)
#     db.commit()
#     try:
#         result = await WhatsAppService().send(normalized, record.mensagem)
#         record.status = "Enviada"
#         record.message_id = str(result.get("message_id") or "")[:255] or None
#         record.enviado_em = datetime.now(timezone.utc)
#         db.commit()
#         return await _page(
#             request, db, success=f"Mensagem enviada para {normalized}."
#         )
#     except WhatsAppServiceError as exc:
#         record.status = "Erro"
#         record.detalhes_erro = str(exc)[:1000]
#         db.commit()
#         return await _page(request, db, error=str(exc), values=values)
