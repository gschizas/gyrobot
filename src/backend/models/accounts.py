import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, Text, UniqueConstraint, \
    func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

_EMPTY_OBJECT = text("'{}'::jsonb")


class AccountRow(Base):
    __tablename__ = 'accounts'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='accounts_pkey'),
        UniqueConstraint('primary_email', name='accounts_primary_email_key'),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str | None] = mapped_column(Text)
    primary_email: Mapped[str] = mapped_column(Text)
    team: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # "metadata" is reserved by SQLAlchemy's declarative base
    metadata_: Mapped[Any] = mapped_column('metadata', JSONB, server_default=_EMPTY_OBJECT)


class ProvisionRow(Base):
    __tablename__ = 'account_provisions'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='account_provisions_pkey'),
        UniqueConstraint('account_id', 'resource', name='account_provisions_account_id_resource_key'),
        Index('idx_account_provisions_resource_status', 'resource', 'status'),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('accounts.id', name='account_provisions_account_id_fkey', ondelete='CASCADE'))
    resource: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    data: Mapped[Any] = mapped_column(JSONB, server_default=_EMPTY_OBJECT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProvisionHistoryRow(Base):
    """Append-only audit trail: one row per provision status write."""
    __tablename__ = 'account_provision_history'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='account_provision_history_pkey'),
        Index('idx_account_provision_history_account', 'account_id', 'resource', 'recorded_at'),
    )

    id: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('accounts.id', name='account_provision_history_account_id_fkey', ondelete='CASCADE'))
    resource: Mapped[str] = mapped_column(Text)
    previous_status: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    data: Mapped[Any] = mapped_column(JSONB, server_default=_EMPTY_OBJECT)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountHistoryRow(Base):
    """Append-only audit trail: a snapshot of the account row on creation and after every update."""
    __tablename__ = 'account_history'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='account_history_pkey'),
        Index('idx_account_history_account', 'account_id', 'recorded_at'),
    )

    id: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('accounts.id', name='account_history_account_id_fkey', ondelete='CASCADE'))
    name: Mapped[str | None] = mapped_column(Text)
    primary_email: Mapped[str | None] = mapped_column(Text)
    team: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[Any] = mapped_column('metadata', JSONB, server_default=_EMPTY_OBJECT)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
