from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, PrimaryKeyConstraint, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ApprovalRequest(Base):
    __tablename__ = 'approval_requests'
    __table_args__ = (PrimaryKeyConstraint('id', name='approval_requests_pkey'),)

    id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requested_by_user_id: Mapped[str | None] = mapped_column(Text)
    requested_by_name: Mapped[str | None] = mapped_column(Text)
    team_id: Mapped[str | None] = mapped_column(Text)
    team_name: Mapped[str | None] = mapped_column(Text)
    channel_id: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str] = mapped_column(Text)
    params: Mapped[Any] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    decided_by_user_id: Mapped[str | None] = mapped_column(Text)
    decided_by_name: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(Text)
