import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, Text, \
    UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

_EMPTY_OBJECT = text("'{}'::jsonb")


class AccountRow(Base):
    __tablename__ = 'accounts'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='accounts_pkey'),
        UniqueConstraint('primary_email', name='accounts_primary_email_key'),
        Index('accounts_primary_email_lower_key', text('lower(primary_email)'), unique=True),
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
        Index('account_provisions_github_username_lower_key', text("lower(data->>'username')"), unique=True,
              postgresql_where=text("resource = 'github'")),
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


class RoleRow(Base):
    """A role a person can hold in a team (e.g. scrum master). Retired roles are deactivated, never deleted."""
    __tablename__ = 'roles'
    __table_args__ = (PrimaryKeyConstraint('key', name='roles_pkey'),)

    key: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    is_team_admin: Mapped[bool] = mapped_column(Boolean, server_default=text('false'))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text('true'))
    # When set, the role is only offered for this canonical team and the teams below it
    team_prefix: Mapped[str | None] = mapped_column(Text)


class MembershipRow(Base):
    """A person in a team, with an optional role. One role per person per team."""
    __tablename__ = 'team_memberships'
    __table_args__ = (
        PrimaryKeyConstraint('account_id', 'team', name='team_memberships_pkey'),
        Index('idx_team_memberships_team', 'team'),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('accounts.id', name='team_memberships_account_id_fkey', ondelete='CASCADE'))
    team: Mapped[str] = mapped_column(Text)
    role_key: Mapped[str | None] = mapped_column(Text, ForeignKey('roles.key', name='team_memberships_role_key_fkey'))
    is_team_admin: Mapped[bool] = mapped_column(Boolean, server_default=text('false'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
