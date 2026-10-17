from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, PrimaryKeyConstraint, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PermissionRule(Base):
    __tablename__ = 'permission_rules'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='permission_rules_pkey'),
        UniqueConstraint('function_name', 'environment', 'role', name='permission_rules_function_name_environment_role_key'),
    )

    id: Mapped[int] = mapped_column(Integer)
    function_name: Mapped[str] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(Text, server_default=text("''"))
    role: Mapped[str] = mapped_column(Text, server_default=text("'default'"))
    users: Mapped[Any] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    channels: Mapped[Any] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    extra: Mapped[Any] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
