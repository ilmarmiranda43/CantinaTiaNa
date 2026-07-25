from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


MONTHS_PT = (
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


@dataclass(frozen=True)
class ReferenceMonth:
    value: str
    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True)
class PurchaseSummary:
    message: str
    total: Decimal
    purchase_count: int
    omitted_count: int


def parse_reference_month(value: str | None) -> ReferenceMonth:
    raw = (value or "").strip()
    try:
        selected = datetime.strptime(raw, "%Y-%m") if raw else datetime.now()
    except ValueError as exc:
        raise ValueError("Informe um mês de referência válido.") from exc

    start = datetime(selected.year, selected.month, 1)
    end = (
        datetime(selected.year + 1, 1, 1)
        if selected.month == 12
        else datetime(selected.year, selected.month + 1, 1)
    )
    return ReferenceMonth(
        value=f"{selected.year:04d}-{selected.month:02d}",
        start=start,
        end=end,
        label=f"{MONTHS_PT[selected.month]}/{selected.year}",
    )


def format_brl(value: Decimal | int | float) -> str:
    formatted = f"{Decimal(value):,.2f}"
    return "R$ " + formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _purchase_block(purchase) -> str:
    lines = [f"📅 {purchase.data.strftime('%d/%m/%Y %H:%M')}"]
    if purchase.itens:
        for item in purchase.itens:
            product_name = item.produto.nome if item.produto else "Produto"
            lines.append(
                "• "
                f"{product_name} — {item.quantidade} x {format_brl(item.preco_unitario)} "
                f"= {format_brl(item.subtotal)}"
            )
    else:
        lines.append("• Lançamento sem itens detalhados")
    lines.append(f"Subtotal: {format_brl(purchase.valor_total)}")
    return "\n".join(lines)


def build_purchase_summary(
    responsavel,
    aluno,
    purchases: list,
    reference: ReferenceMonth,
    *,
    max_length: int = 4096,
) -> PurchaseSummary:
    total = sum((Decimal(item.valor_total) for item in purchases), Decimal("0"))
    header = (
        f"Olá, {responsavel.nome}!\n\n"
        f"Segue a lista de compras de *{aluno.nome}* referente a "
        f"*{reference.label}*:"
    )
    footer = (
        f"\n\nQuantidade de compras: {len(purchases)}\n"
        f"*TOTAL DO PERÍODO: {format_brl(total)}*"
    )

    if not purchases:
        message = (
            f"{header}\n\nNão houve compras registradas neste período."
            f"{footer}"
        )
        return PurchaseSummary(message, total, 0, 0)

    blocks: list[str] = []
    omitted = 0
    for index, purchase in enumerate(purchases):
        block = _purchase_block(purchase)
        candidate = f"{header}\n\n" + "\n\n".join(blocks + [block]) + footer
        if len(candidate) > max_length:
            omitted = len(purchases) - index
            break
        blocks.append(block)

    if omitted:
        notice = f"… {omitted} compra(s) omitida(s) para respeitar o limite da mensagem."
        while blocks:
            candidate = (
                f"{header}\n\n"
                + "\n\n".join(blocks + [notice])
                + footer
            )
            if len(candidate) <= max_length:
                break
            blocks.pop()
            omitted += 1
        body = "\n\n".join(blocks + [notice])
    else:
        body = "\n\n".join(blocks)

    message = f"{header}\n\n{body}{footer}"
    if len(message) > max_length:
        message = f"{header}\n\nResumo extenso demais para detalhamento.{footer}"

    return PurchaseSummary(message, total, len(purchases), omitted)

