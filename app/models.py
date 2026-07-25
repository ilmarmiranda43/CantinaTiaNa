from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "AspNetUsers"

    id: Mapped[str] = mapped_column("Id", Text, primary_key=True)
    user_name: Mapped[str | None] = mapped_column("UserName", String(256))
    normalized_user_name: Mapped[str | None] = mapped_column("NormalizedUserName", String(256), unique=True)
    email: Mapped[str | None] = mapped_column("Email", String(256))
    normalized_email: Mapped[str | None] = mapped_column("NormalizedEmail", String(256), index=True)
    email_confirmed: Mapped[bool] = mapped_column("EmailConfirmed", Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column("PasswordHash", Text)
    security_stamp: Mapped[str | None] = mapped_column("SecurityStamp", Text)
    concurrency_stamp: Mapped[str | None] = mapped_column("ConcurrencyStamp", Text)
    phone_number: Mapped[str] = mapped_column("PhoneNumber", Text, default="")
    phone_number_confirmed: Mapped[bool] = mapped_column("PhoneNumberConfirmed", Boolean, default=False)
    two_factor_enabled: Mapped[bool] = mapped_column("TwoFactorEnabled", Boolean, default=False)
    lockout_end: Mapped[datetime | None] = mapped_column("LockoutEnd", DateTime(timezone=True))
    lockout_enabled: Mapped[bool] = mapped_column("LockoutEnabled", Boolean, default=True)
    access_failed_count: Mapped[int] = mapped_column("AccessFailedCount", Integer, default=0)
    nome: Mapped[str] = mapped_column("Nome", Text, default="")
    ra: Mapped[str] = mapped_column("RA", Text, default="")
    pode_enviar_whatsapp: Mapped[bool] = mapped_column("PodeEnviarWhatsApp", Boolean, default=False)


class Role(Base):
    __tablename__ = "AspNetRoles"

    id: Mapped[str] = mapped_column("Id", Text, primary_key=True)
    name: Mapped[str | None] = mapped_column("Name", String(256))
    normalized_name: Mapped[str | None] = mapped_column("NormalizedName", String(256), unique=True)
    concurrency_stamp: Mapped[str | None] = mapped_column("ConcurrencyStamp", Text)


class UserRole(Base):
    __tablename__ = "AspNetUserRoles"

    user_id: Mapped[str] = mapped_column(
        "UserId", ForeignKey("AspNetUsers.Id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        "RoleId", ForeignKey("AspNetRoles.Id", ondelete="CASCADE"), primary_key=True
    )


class Responsavel(Base):
    __tablename__ = "Responsaveis"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column("Nome", Text)
    valor_para_cantina: Mapped[Decimal] = mapped_column(
        "ValorParaCantina", Numeric(18, 2), default=Decimal("0")
    )
    fone: Mapped[str | None] = mapped_column("Fone", Text)
    email: Mapped[str | None] = mapped_column("Email", Text)
    dia_pgto: Mapped[int | None] = mapped_column("DiaPgto", Integer)

    alunos: Mapped[list["Aluno"]] = relationship(back_populates="responsavel")


class Aluno(Base):
    __tablename__ = "Alunos"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column("Nome", Text)
    data_nascimento: Mapped[datetime] = mapped_column("DataNascimento", DateTime(timezone=False))
    serie: Mapped[str] = mapped_column("Serie", Text)
    valor_disponivel: Mapped[Decimal] = mapped_column("ValorDisponivel", Numeric, default=Decimal("0"))
    responsavel_id: Mapped[int] = mapped_column(
        "ResponsavelId", ForeignKey("Responsaveis.Id", ondelete="RESTRICT")
    )
    application_user_id: Mapped[str | None] = mapped_column(
        "ApplicationUserId", ForeignKey("AspNetUsers.Id", ondelete="SET NULL")
    )

    responsavel: Mapped[Responsavel] = relationship(back_populates="alunos")
    usuario: Mapped[User | None] = relationship()
    compras: Mapped[list["Compra"]] = relationship(back_populates="aluno")


class Produto(Base):
    __tablename__ = "Produtos"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column("Nome", String(120))
    preco: Mapped[Decimal] = mapped_column("Preco", Numeric(18, 2))
    quantidade: Mapped[int] = mapped_column("Quantidade", Integer, default=0)
    categoria: Mapped[str | None] = mapped_column("Categoria", String(80))
    data_cadastro: Mapped[datetime] = mapped_column(
        "DataCadastro", DateTime(timezone=False), default=datetime.now
    )


class Compra(Base):
    __tablename__ = "Compras"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    aluno_id: Mapped[int] = mapped_column("AlunoId", ForeignKey("Alunos.Id", ondelete="RESTRICT"))
    data: Mapped[datetime] = mapped_column("Data", DateTime(timezone=False), default=datetime.now)
    valor_total: Mapped[Decimal] = mapped_column("ValorTotal", Numeric(18, 2))

    aluno: Mapped[Aluno] = relationship(back_populates="compras")
    itens: Mapped[list["CompraItem"]] = relationship(
        back_populates="compra", cascade="all, delete-orphan"
    )


class CompraItem(Base):
    __tablename__ = "CompraItens"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    compra_id: Mapped[int] = mapped_column(
        "CompraId", ForeignKey("Compras.Id", ondelete="CASCADE")
    )
    produto_id: Mapped[int] = mapped_column(
        "ProdutoId", ForeignKey("Produtos.Id", ondelete="RESTRICT")
    )
    quantidade: Mapped[int] = mapped_column("Quantidade", Integer)
    preco_unitario: Mapped[Decimal] = mapped_column("PrecoUnitario", Numeric(18, 2))

    compra: Mapped[Compra] = relationship(back_populates="itens")
    produto: Mapped[Produto] = relationship()

    @property
    def subtotal(self) -> Decimal:
        return self.quantidade * self.preco_unitario


class Venda(Base):
    __tablename__ = "Vendas"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    data_venda: Mapped[datetime] = mapped_column(
        "DataVenda", DateTime(timezone=False), default=datetime.now
    )
    cliente_nome: Mapped[str | None] = mapped_column("ClienteNome", String(120))
    forma_pagamento: Mapped[str | None] = mapped_column("FormaPagamento", String(40))
    total: Mapped[Decimal] = mapped_column("Total", Numeric(18, 2), default=Decimal("0"))

    itens: Mapped[list["VendaItem"]] = relationship(
        back_populates="venda", cascade="all, delete-orphan"
    )


class VendaItem(Base):
    __tablename__ = "VendasItens"

    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    venda_id: Mapped[int] = mapped_column("VendaId", ForeignKey("Vendas.Id", ondelete="CASCADE"))
    produto_id: Mapped[int] = mapped_column(
        "ProdutoId", ForeignKey("Produtos.Id", ondelete="RESTRICT")
    )
    quantidade: Mapped[int] = mapped_column("Quantidade", Integer)
    preco_unitario: Mapped[Decimal] = mapped_column("PrecoUnitario", Numeric(18, 2))

    venda: Mapped[Venda] = relationship(back_populates="itens")
    produto: Mapped[Produto] = relationship()


class WhatsAppMensagem(Base):
    __tablename__ = "WhatsAppMensagens"
    __table_args__ = (
        Index("IX_WhatsAppMensagens_CriadoEm", "CriadoEm"),
        Index("IX_WhatsAppMensagens_UsuarioId", "UsuarioId"),
    )

    id: Mapped[int] = mapped_column(
        "Id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    usuario_id: Mapped[str | None] = mapped_column(
        "UsuarioId", ForeignKey("AspNetUsers.Id", ondelete="SET NULL")
    )
    usuario_nome: Mapped[str] = mapped_column("UsuarioNome", String(256))
    responsavel_id: Mapped[int | None] = mapped_column(
        "ResponsavelId", ForeignKey("Responsaveis.Id", ondelete="SET NULL")
    )
    telefone: Mapped[str] = mapped_column("Telefone", String(20))
    mensagem: Mapped[str] = mapped_column("Mensagem", String(4096))
    status: Mapped[str] = mapped_column("Status", String(30), default="Pendente")
    message_id: Mapped[str | None] = mapped_column("MessageId", String(255))
    detalhes_erro: Mapped[str | None] = mapped_column("DetalhesErro", String(1000))
    criado_em: Mapped[datetime] = mapped_column(
        "CriadoEm", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    enviado_em: Mapped[datetime | None] = mapped_column("EnviadoEm", DateTime(timezone=True))

    usuario: Mapped[User | None] = relationship()
    responsavel: Mapped[Responsavel | None] = relationship()
